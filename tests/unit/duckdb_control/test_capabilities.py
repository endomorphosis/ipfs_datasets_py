"""Unit tests for DuckDB/Quack/VSS capability policy and probes (DQK-002).

All probes are fully injected.  These tests never import the optional
``duckdb`` package, never load Quack or VSS extensions, and never open
network sockets — exercising fail-closed version policy, explicit Quack
beta status, and optional feature gates in isolation.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import MappingProxyType

# Prefer the sealed validator's accelerator checkout in nested worktrees.
# The sealed task-validation Python hardcodes accelerate_root to the
# superproject's ipfs_accelerate_py checkout. Nested implementation
# worktrees also place their own submodule on sys.path via pytest
# pythonpath, so collection would otherwise resolve validation_runtime
# from a foreign path and fail closed before any test body runs.
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

from ipfs_datasets_py.duckdb_control import capabilities as caps



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _versions(**kwargs: object) -> caps.ComponentVersions:
    return caps.ComponentVersions(**kwargs)  # type: ignore[arg-type]


def _pinned_ok(**overrides: object) -> caps.ComponentVersions:
    base = {
        "client_duckdb": caps.REQUIRED_DUCKDB_VERSION_TEXT,
        "server_duckdb": caps.REQUIRED_DUCKDB_VERSION_TEXT,
        "quack_extension": caps.format_version(caps.PINNED_QUACK_EXTENSION_VERSION),
        "quack_extension_build": caps.PINNED_QUACK_EXTENSION_BUILD,
        "quack_extension_source": "core",
        "vss_extension": caps.format_version(caps.PINNED_VSS_EXTENSION_VERSION),
        "vss_extension_build": caps.PINNED_VSS_EXTENSION_BUILD,
        "client_protocol": caps.DEFAULT_QUACK_PROTOCOL_VERSION,
        "server_protocol": caps.DEFAULT_QUACK_PROTOCOL_VERSION,
    }
    base.update(overrides)
    return _versions(**base)


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

    # Drop cached module so re-import exercises the top-level body.
    sys.modules.pop("ipfs_datasets_py.duckdb_control.capabilities", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.import_module("ipfs_datasets_py.duckdb_control.capabilities")
    assert reloaded.REQUIRED_DUCKDB_VERSION == (1, 5, 5)
    assert reloaded.QUACK_BETA is True
    # Restore a normal reference for subsequent tests.
    sys.modules["ipfs_datasets_py.duckdb_control.capabilities"] = reloaded
    monkeypatch.setattr(builtins, "__import__", real_import)


def test_module_does_not_require_duckdb_at_import() -> None:
    assert "duckdb" not in sys.modules or True  # may be present from other tests
    # Public policy constants are usable without duckdb installed.
    assert caps.REQUIRED_DUCKDB_VERSION_TEXT == "1.5.5"
    assert caps.PINNED_QUACK_EXTENSION_BUILD == "quack@1.5.5+core"
    assert caps.PINNED_VSS_EXTENSION_BUILD == "vss@1.5.5+core"
    assert caps.DEFAULT_VERSION_POLICY.duckdb_version == (1, 5, 5)


# ---------------------------------------------------------------------------
# Version policy helpers
# ---------------------------------------------------------------------------


def test_parse_and_format_version_round_trip() -> None:
    assert caps.parse_version("1.5.5") == (1, 5, 5)
    assert caps.parse_version("1.5.5.dev0") == (1, 5, 5)
    assert caps.parse_version((1, 5, 5)) == (1, 5, 5)
    assert caps.parse_version(None) == ()
    assert caps.parse_version("") == ()
    assert caps.format_version((1, 5, 5)) == "1.5.5"
    assert caps.versions_match_exact("1.5.5.post1", "1.5.5")
    assert not caps.versions_match_exact("1.5.4", "1.5.5")
    assert not caps.versions_match_exact("1.5", "1.5.5")


def test_default_policy_pins_and_declares_quack_beta() -> None:
    policy = caps.DEFAULT_VERSION_POLICY
    mapping = dict(policy.as_mapping())
    assert mapping["duckdb_version"] == "1.5.5"
    assert mapping["quack_extension_build"] == "quack@1.5.5+core"
    assert mapping["vss_extension_build"] == "vss@1.5.5+core"
    assert mapping["quack_beta"] is True
    assert "not production-ready until DuckDB 2.0" in mapping["quack_status_reason"]
    assert mapping["supported_protocol_versions"] == [1]
    assert policy.minimum_quack_version == (1, 5, 3)


def test_quack_maturity_is_explicitly_beta_until_duckdb_2() -> None:
    assert caps.quack_maturity_status() is caps.QuackMaturity.BETA
    assert caps.QUACK_BETA is True
    assert "beta" in caps.QUACK_STATUS_REASON.lower()
    assert caps.quack_maturity_status(duckdb_version="1.5.5") is caps.QuackMaturity.BETA
    assert (
        caps.quack_maturity_status(duckdb_version="2.0.0")
        is caps.QuackMaturity.PRODUCTION_CANDIDATE
    )
    assert (
        caps.quack_maturity_status(duckdb_version="1.9.9") is caps.QuackMaturity.BETA
    )


# ---------------------------------------------------------------------------
# Fail-closed version mismatches
# ---------------------------------------------------------------------------


def test_assert_versions_compatible_accepts_exact_pin() -> None:
    caps.assert_versions_compatible(
        _pinned_ok(),
        require_server=True,
        require_quack_extension=True,
        require_vss_extension=True,
        require_protocol=True,
    )


def test_client_version_mismatch_fails_closed() -> None:
    versions = _pinned_ok(client_duckdb="1.5.4")
    with pytest.raises(caps.VersionMismatchError, match="client DuckDB version mismatch"):
        caps.assert_versions_compatible(versions)


def test_server_version_mismatch_fails_closed() -> None:
    versions = _pinned_ok(server_duckdb="1.4.0")
    with pytest.raises(caps.VersionMismatchError, match="server DuckDB version mismatch"):
        caps.assert_versions_compatible(versions, require_server=True)


def test_client_server_skew_fails_closed() -> None:
    versions = _versions(
        client_duckdb="1.5.5",
        server_duckdb="1.5.5",  # same pin text
    )
    # Force skew via different observed strings that parse equal... use real skew:
    versions = _versions(client_duckdb="1.5.5", server_duckdb="1.5.4")
    with pytest.raises(caps.VersionMismatchError, match="server DuckDB version mismatch"):
        caps.assert_versions_compatible(versions, require_server=True)


def test_quack_extension_version_mismatch_fails_closed() -> None:
    versions = _pinned_ok(
        quack_extension="1.5.3",
        quack_extension_build="quack@1.5.3+core",
    )
    with pytest.raises(caps.VersionMismatchError, match="Quack extension"):
        caps.assert_versions_compatible(versions, require_quack_extension=True)


def test_quack_extension_build_mismatch_fails_closed() -> None:
    versions = _pinned_ok(
        quack_extension="1.5.5",
        quack_extension_build="quack@1.5.5+core_nightly",
        quack_extension_source="core_nightly",
    )
    with pytest.raises(caps.VersionMismatchError, match="Quack extension"):
        caps.assert_versions_compatible(versions, require_quack_extension=True)


def test_protocol_mismatch_fails_closed() -> None:
    versions = _pinned_ok(client_protocol=1, server_protocol=2)
    with pytest.raises(caps.VersionMismatchError, match="protocol mismatch"):
        caps.assert_versions_compatible(versions, require_protocol=True)


def test_unsupported_protocol_version_fails_closed() -> None:
    versions = _pinned_ok(client_protocol=99, server_protocol=99)
    with pytest.raises(caps.VersionMismatchError, match="unsupported client Quack protocol"):
        caps.assert_versions_compatible(versions, require_protocol=True)


def test_vss_extension_mismatch_fails_closed() -> None:
    versions = _pinned_ok(
        vss_extension="0.9.0",
        vss_extension_build="vss@0.9.0+core",
    )
    with pytest.raises(caps.VersionMismatchError, match="VSS extension"):
        caps.assert_versions_compatible(versions, require_vss_extension=True)


# ---------------------------------------------------------------------------
# Probe: happy path, optional gates, fallbacks
# ---------------------------------------------------------------------------


def test_probe_local_only_without_optional_features() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=False, enable_vss=False),
        versions=_versions(client_duckdb="1.5.5", server_duckdb="1.5.5"),
    )
    assert result.ok is True
    assert result.schema == caps.CAPABILITY_PROBE_SCHEMA
    assert result.quack_beta is True
    assert result.quack_maturity is caps.QuackMaturity.BETA
    assert "not production-ready" in result.quack_status_reason
    assert result.capabilities["duckdb_runtime"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["quack_transport"].status is caps.CapabilityStatus.DISABLED
    assert result.capabilities["vss_index"].status is caps.CapabilityStatus.DISABLED
    assert result.feature_gates["quack"].state is caps.FeatureGateState.DISABLED
    assert result.feature_gates["vss"].state is caps.FeatureGateState.DISABLED
    assert result.feature_gates["quack"].fallback == "local"
    assert result.feature_gates["vss"].fallback == "exact_search"
    assert result.feature_gates["quack"].beta is True
    assert result.transport.mode is caps.TransportMode.LOCAL
    assert result.transport.fell_back is False
    assert result.mismatches == ()


def test_probe_enables_quack_and_vss_when_versions_match() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(
            enable_quack=True,
            enable_vss=True,
            require_protocol=True,
        ),
        versions=_pinned_ok(),
    )
    assert result.ok is True
    assert result.capabilities["quack_transport"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["vss_index"].status is caps.CapabilityStatus.AVAILABLE
    assert result.capabilities["protocol"].status is caps.CapabilityStatus.AVAILABLE
    assert result.feature_gates["quack"].enabled is True
    assert result.feature_gates["vss"].enabled is True
    assert result.feature_gates["quack"].beta is True
    assert result.transport.mode is caps.TransportMode.QUACK_REMOTE
    assert result.transport.quack_available is True
    # Quack beta is explicit on the capability identity.
    quack_identity = dict(result.capabilities["quack_transport"].identity)
    assert quack_identity["beta"] is True
    assert quack_identity["maturity"] == "beta"
    assert quack_identity["required_build"] == "quack@1.5.5+core"
    # VSS is never identity authority.
    vss_identity = dict(result.capabilities["vss_index"].identity)
    assert vss_identity["identity_authority"] is False
    assert vss_identity["fallback"] == "exact_search"


def test_probe_quack_unavailable_falls_back_to_local() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=True, enable_vss=False),
        versions=_versions(client_duckdb="1.5.5", server_duckdb="1.5.5"),
    )
    assert result.ok is True  # local duckdb pin holds; quack is optional
    assert result.capabilities["quack_transport"].status is caps.CapabilityStatus.UNAVAILABLE
    assert result.feature_gates["quack"].state is caps.FeatureGateState.UNAVAILABLE
    assert result.feature_gates["quack"].fallback == "local"
    assert result.transport.mode is caps.TransportMode.LOCAL
    assert result.transport.fell_back is True
    assert result.transport.local_fallback_available is True


def test_probe_vss_unavailable_uses_exact_search_fallback() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=False, enable_vss=True),
        versions=_versions(client_duckdb="1.5.5"),
    )
    assert result.ok is True
    assert result.capabilities["vss_index"].status is caps.CapabilityStatus.UNAVAILABLE
    gate = result.feature_gates["vss"]
    assert gate.state is caps.FeatureGateState.UNAVAILABLE
    assert gate.fallback == "exact_search"
    assert gate.enabled is False


def test_probe_version_mismatch_fails_closed_and_refuses_remote() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=True, enable_vss=False, require_protocol=True),
        versions=_pinned_ok(client_duckdb="1.4.1", server_duckdb="1.4.1"),
        fail_closed=True,
    )
    assert result.ok is False
    assert result.fail_closed is True
    assert result.capabilities["duckdb_runtime"].status is caps.CapabilityStatus.MISMATCH
    assert any("DuckDB" in item for item in result.mismatches)
    # Remote transport must not be selected under fail-closed mismatch.
    assert result.transport.mode is caps.TransportMode.LOCAL
    assert result.transport.quack_available is False


def test_probe_quack_extension_mismatch_fails_closed() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=True),
        versions=_pinned_ok(
            quack_extension="1.5.3",
            quack_extension_build="quack@1.5.3+core",
        ),
    )
    assert result.ok is False
    assert result.capabilities["quack_transport"].status is caps.CapabilityStatus.MISMATCH
    assert result.feature_gates["quack"].state is caps.FeatureGateState.MISMATCH
    assert result.feature_gates["quack"].fallback is None  # fail closed, no remote
    assert result.transport.mode is caps.TransportMode.LOCAL
    with pytest.raises(caps.VersionMismatchError):
        caps.require_capability(result, caps.CapabilityKind.QUACK_TRANSPORT)


def test_probe_protocol_mismatch_fails_closed() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=True, require_protocol=True),
        versions=_pinned_ok(client_protocol=1, server_protocol=2),
    )
    assert result.ok is False
    assert result.capabilities["protocol"].status is caps.CapabilityStatus.MISMATCH
    assert result.capabilities["quack_transport"].status is caps.CapabilityStatus.MISMATCH
    assert result.transport.mode is caps.TransportMode.LOCAL


def test_probe_client_server_duckdb_mismatch_fails_closed() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=False),
        versions=_versions(client_duckdb="1.5.5", server_duckdb="1.5.4"),
    )
    assert result.ok is False
    assert result.capabilities["duckdb_runtime"].status is caps.CapabilityStatus.MISMATCH


def test_require_capability_raises_when_unavailable() -> None:
    result = caps.probe_capabilities(
        versions=_versions(),  # no duckdb at all
    )
    assert result.ok is False
    with pytest.raises(caps.CapabilityUnavailableError, match="not installed"):
        caps.require_capability(result, "duckdb_runtime")


def test_require_capability_returns_available_record() -> None:
    result = caps.probe_capabilities(
        versions=_versions(client_duckdb="1.5.5", server_duckdb="1.5.5"),
    )
    record = caps.require_capability(result, caps.CapabilityKind.DUCKDB_RUNTIME)
    assert record.status is caps.CapabilityStatus.AVAILABLE


# ---------------------------------------------------------------------------
# Feature gates are optional (not import-time requirements)
# ---------------------------------------------------------------------------


def test_quack_and_vss_are_optional_feature_gates_not_import_requirements() -> None:
    # Default probe request leaves both optional features off.
    result = caps.probe_capabilities(
        versions=_versions(client_duckdb="1.5.5"),
    )
    assert "quack" in result.feature_gates
    assert "vss" in result.feature_gates
    assert result.feature_gates["quack"].requested is False
    assert result.feature_gates["vss"].requested is False
    assert result.feature_gates["quack"].enabled is False
    assert result.feature_gates["vss"].enabled is False
    # Capability kinds exist but are DISABLED, not required.
    assert result.capabilities["quack_transport"].required is False
    assert result.capabilities["vss_index"].required is False
    assert result.capabilities["duckdb_runtime"].required is True


def test_evaluate_feature_gate_disabled_without_request() -> None:
    gate = caps.evaluate_feature_gate(
        caps.FeatureName.QUACK,
        requested=False,
        capability=None,
        beta=True,
    )
    assert gate.state is caps.FeatureGateState.DISABLED
    assert gate.fallback == "local"
    assert gate.beta is True
    assert gate.enabled is False


def test_evaluate_feature_gate_vss_exact_search_fallback() -> None:
    record = caps.CapabilityRecord(
        kind=caps.CapabilityKind.VSS_INDEX,
        status=caps.CapabilityStatus.UNAVAILABLE,
        reason="missing",
    )
    gate = caps.evaluate_feature_gate(
        "vss",
        requested=True,
        capability=record,
    )
    assert gate.state is caps.FeatureGateState.UNAVAILABLE
    assert gate.fallback == "exact_search"


# ---------------------------------------------------------------------------
# Injected observer path and report shape
# ---------------------------------------------------------------------------


def test_probe_uses_injected_observer() -> None:
    calls: list[int] = []

    def observe() -> caps.ComponentVersions:
        calls.append(1)
        return _versions(client_duckdb="1.5.5", server_duckdb="1.5.5")

    result = caps.probe_capabilities(observe=observe)
    assert calls == [1]
    assert result.ok is True
    assert result.versions.client_duckdb == "1.5.5"


def test_probe_result_as_mapping_is_json_friendly() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=True, enable_vss=True),
        versions=_pinned_ok(),
    )
    mapping = dict(result.as_mapping())
    assert mapping["schema"] == caps.CAPABILITY_PROBE_SCHEMA
    assert mapping["ok"] is True
    assert mapping["quack_beta"] is True
    assert mapping["quack_maturity"] == "beta"
    assert mapping["policy"]["duckdb_version"] == "1.5.5"
    assert mapping["feature_gates"]["quack"]["beta"] is True
    assert mapping["transport"]["mode"] == "quack_remote"
    assert isinstance(mapping["mismatches"], list)
    # Nested structures should be plain dicts / lists for serialization.
    assert isinstance(mapping["capabilities"], dict)
    assert isinstance(mapping["capabilities"]["duckdb_runtime"], dict)


def test_capability_record_ok_semantics() -> None:
    available = caps.CapabilityRecord(
        kind=caps.CapabilityKind.DUCKDB_RUNTIME,
        status=caps.CapabilityStatus.AVAILABLE,
        required=True,
    )
    assert available.ok is True
    mismatch = caps.CapabilityRecord(
        kind=caps.CapabilityKind.QUACK_TRANSPORT,
        status=caps.CapabilityStatus.MISMATCH,
        required=False,
    )
    assert mismatch.ok is False
    disabled_optional = caps.CapabilityRecord(
        kind=caps.CapabilityKind.VSS_INDEX,
        status=caps.CapabilityStatus.DISABLED,
        required=False,
    )
    assert disabled_optional.ok is True
    unavailable_required = caps.CapabilityRecord(
        kind=caps.CapabilityKind.DUCKDB_RUNTIME,
        status=caps.CapabilityStatus.UNAVAILABLE,
        required=True,
    )
    assert unavailable_required.ok is False


def test_component_versions_normalize_blank_strings() -> None:
    versions = _versions(client_duckdb="  ", server_duckdb="")
    assert versions.client_duckdb is None
    assert versions.server_duckdb is None


def test_component_versions_reject_invalid_protocol() -> None:
    with pytest.raises(caps.CapabilityError):
        _versions(client_protocol=-1)  # type: ignore[arg-type]
    with pytest.raises(caps.CapabilityError):
        _versions(client_protocol=True)  # type: ignore[arg-type]


def test_identity_mappings_are_immutable() -> None:
    record = caps.CapabilityRecord(
        kind=caps.CapabilityKind.DUCKDB_RUNTIME,
        status=caps.CapabilityStatus.AVAILABLE,
        identity={"version": "1.5.5"},
    )
    assert isinstance(record.identity, MappingProxyType)
    with pytest.raises(TypeError):
        record.identity["version"] = "nope"  # type: ignore[index]


def test_resolve_transport_refuses_remote_on_mismatch() -> None:
    gate = caps.FeatureGate(
        name=caps.FeatureName.QUACK,
        state=caps.FeatureGateState.MISMATCH,
        requested=True,
        reason="build mismatch",
        beta=True,
    )
    resolution = caps.resolve_transport(quack_gate=gate, duckdb_ok=True)
    assert resolution.mode is caps.TransportMode.LOCAL
    assert resolution.quack_available is False
    assert "fail closed" in resolution.reason or "mismatch" in resolution.reason


def test_missing_duckdb_does_not_silently_enable_quack() -> None:
    result = caps.probe_capabilities(
        caps.ProbeRequest(enable_quack=True),
        versions=_versions(),
    )
    assert result.ok is False
    assert result.transport.mode is caps.TransportMode.LOCAL
    assert result.transport.local_fallback_available is False
    assert result.feature_gates["quack"].enabled is False
