"""Contract tests for LogicPlatformManifest@1 handshake (LPC-100).

Acceptance:

* handshake works from wheels without sibling repos or Git metadata
* Git / source commit remains optional provenance only
* incompatible versions return a typed incompatibility result
* local repository layout is never semantic compatibility authority
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.families.canonical_catalog import (
    CANONICAL_CATALOG_SNAPSHOT_INTERFACE,
    DEFAULT_CANONICAL_CATALOG_SNAPSHOT,
)
from ipfs_datasets_py.logic.platform.manifest import (
    DEFAULT_COMPATIBLE_ADAPTER_VERSIONS,
    DEFAULT_LOGIC_PLATFORM_MANIFEST,
    HANDSHAKE_RESULT_SCHEMA,
    LOGIC_PLATFORM_MANIFEST_GOAL_ID,
    LOGIC_PLATFORM_MANIFEST_INTERFACE,
    LOGIC_PLATFORM_MANIFEST_SCHEMA,
    LOGIC_PLATFORM_MANIFEST_TASK_ID,
    LOGIC_PLATFORM_MANIFEST_VERSION,
    PACKAGE_NAME,
    HandshakeRequirements,
    HandshakeResult,
    IncompatibilityCode,
    LogicPlatformManifest,
    LogicPlatformManifestError,
    ManifestIncompatibility,
    build_logic_platform_manifest,
    handshake,
    optional_source_commit,
    resolve_package_version,
)


# ---------------------------------------------------------------------------
# Interface / construction surface
# ---------------------------------------------------------------------------


def test_default_manifest_interface_and_task_binding() -> None:
    manifest = DEFAULT_LOGIC_PLATFORM_MANIFEST
    assert manifest.interface == LOGIC_PLATFORM_MANIFEST_INTERFACE
    assert manifest.interface == "LogicPlatformManifest@1"
    assert manifest.schema_version == LOGIC_PLATFORM_MANIFEST_SCHEMA
    assert manifest.version == LOGIC_PLATFORM_MANIFEST_VERSION
    assert manifest.task_id == LOGIC_PLATFORM_MANIFEST_TASK_ID
    assert manifest.goal_id == LOGIC_PLATFORM_MANIFEST_GOAL_ID
    assert manifest.task_id == "LPC-100"
    assert manifest.goal_id == "LPC-G100"
    assert manifest.package_name == PACKAGE_NAME


def test_builder_matches_default_catalog_root() -> None:
    rebuilt = build_logic_platform_manifest(include_source_commit=False)
    assert rebuilt.catalog_root == DEFAULT_CANONICAL_CATALOG_SNAPSHOT.content_root
    assert rebuilt.catalog_digest == DEFAULT_CANONICAL_CATALOG_SNAPSHOT.content_digest
    assert rebuilt.catalog_digest.startswith("sha256:")
    assert rebuilt.interface_versions[CANONICAL_CATALOG_SNAPSHOT_INTERFACE]


def test_manifest_exposes_required_version_maps() -> None:
    manifest = DEFAULT_LOGIC_PLATFORM_MANIFEST
    assert LOGIC_PLATFORM_MANIFEST_INTERFACE in manifest.interface_versions
    assert "catalog_snapshot" in manifest.schema_roots
    assert "handshake" in manifest.operation_versions
    assert "handshake_result" in manifest.receipt_versions
    assert "goal_directed_proof_plan" in manifest.plan_versions
    assert "SupervisorLogicPlatformClient@1" in manifest.compatible_adapter_versions
    assert tuple(manifest.compatible_adapter_versions) == DEFAULT_COMPATIBLE_ADAPTER_VERSIONS


def test_manifest_is_immutable() -> None:
    manifest = DEFAULT_LOGIC_PLATFORM_MANIFEST
    with pytest.raises(FrozenInstanceError):
        manifest.package_version = "9.9.9"  # type: ignore[misc]
    assert isinstance(manifest.interface_versions, MappingProxyType)


def test_to_dict_is_json_ready_and_stable() -> None:
    payload = DEFAULT_LOGIC_PLATFORM_MANIFEST.to_dict()
    assert payload["interface"] == "LogicPlatformManifest@1"
    assert payload["requires_git"] is False
    assert payload["requires_sibling_repos"] is False
    assert payload["requires_repository_layout"] is False
    assert set(payload["interface_versions"]) >= {
        LOGIC_PLATFORM_MANIFEST_INTERFACE,
        CANONICAL_CATALOG_SNAPSHOT_INTERFACE,
    }


# ---------------------------------------------------------------------------
# Wheel / no-Git / no-sibling guarantees
# ---------------------------------------------------------------------------


def test_manifest_does_not_require_git_or_siblings() -> None:
    manifest = build_logic_platform_manifest(
        package_version="0.2.0",
        include_source_commit=False,
        environ={},
    )
    assert manifest.requires_git() is False
    assert manifest.requires_sibling_repos() is False
    assert manifest.requires_repository_layout() is False
    assert manifest.source_commit is None
    assert manifest.git_provenance_available is False


def test_optional_source_commit_ignores_git_and_reads_env_only() -> None:
    assert optional_source_commit(environ={}) is None
    assert (
        optional_source_commit(
            environ={"LOGIC_PLATFORM_SOURCE_COMMIT": "abc123def"}
        )
        == "abc123def"
    )
    assert optional_source_commit(explicit="  deadbeef  ") == "deadbeef"
    # Explicit empty / whitespace is treated as absent provenance.
    assert optional_source_commit(explicit="   ") is None


def test_resolve_package_version_does_not_need_git() -> None:
    version = resolve_package_version(PACKAGE_NAME, fallback="0.2.0")
    assert isinstance(version, str)
    assert version.strip()
    # Fallback is used only when distributions are unavailable.
    assert resolve_package_version(
        "definitely-not-an-installed-dist-xyz",
        fallback="1.2.3",
    ) in {"1.2.3", resolve_package_version(PACKAGE_NAME, fallback="1.2.3")}


def test_handshake_succeeds_without_source_commit() -> None:
    manifest = build_logic_platform_manifest(
        package_version="0.2.0",
        include_source_commit=False,
        environ={},
    )
    result = handshake(HandshakeRequirements(), manifest=manifest)
    assert result.compatible is True
    assert result.incompatibilities == ()
    assert result.manifest.source_commit is None
    assert result.schema_version == HANDSHAKE_RESULT_SCHEMA


def test_default_handshake_without_requirements_is_compatible() -> None:
    result = handshake()
    assert result.compatible is True
    assert result.manifest.interface == LOGIC_PLATFORM_MANIFEST_INTERFACE


# ---------------------------------------------------------------------------
# Typed incompatibility results
# ---------------------------------------------------------------------------


def test_incompatible_manifest_interface_is_typed() -> None:
    result = handshake(
        HandshakeRequirements(required_manifest_interface="LogicPlatformManifest@99"),
        manifest=DEFAULT_LOGIC_PLATFORM_MANIFEST,
    )
    assert result.compatible is False
    assert len(result.incompatibilities) == 1
    finding = result.incompatibilities[0]
    assert finding.code is IncompatibilityCode.MANIFEST_INTERFACE
    assert finding.expected == "LogicPlatformManifest@99"
    assert finding.actual == LOGIC_PLATFORM_MANIFEST_INTERFACE


def test_incompatible_package_version_is_typed() -> None:
    manifest = build_logic_platform_manifest(
        package_version="0.1.0",
        include_source_commit=False,
    )
    result = handshake(
        HandshakeRequirements(min_package_version="9.0.0"),
        manifest=manifest,
    )
    assert result.compatible is False
    codes = {item.code for item in result.incompatibilities}
    assert IncompatibilityCode.PACKAGE_VERSION in codes


def test_exact_package_version_mismatch() -> None:
    manifest = build_logic_platform_manifest(
        package_version="0.2.0",
        include_source_commit=False,
    )
    result = handshake(
        HandshakeRequirements(exact_package_version="0.9.9"),
        manifest=manifest,
    )
    assert result.compatible is False
    assert result.incompatibilities[0].code is IncompatibilityCode.PACKAGE_VERSION


def test_missing_interface_version_is_typed() -> None:
    result = handshake(
        HandshakeRequirements(
            required_interface_versions={
                "DoesNotExistInterface@1": "1.0.0",
            }
        ),
        manifest=DEFAULT_LOGIC_PLATFORM_MANIFEST,
    )
    assert result.compatible is False
    assert result.incompatibilities[0].code is IncompatibilityCode.INTERFACE_VERSION
    assert result.incompatibilities[0].actual == ""


def test_schema_root_and_operation_mismatches_are_typed() -> None:
    result = handshake(
        HandshakeRequirements(
            required_schema_roots={"catalog_snapshot": "wrong-schema/v9"},
            required_operation_versions={"handshake": "99.0.0"},
        ),
        manifest=DEFAULT_LOGIC_PLATFORM_MANIFEST,
    )
    assert result.compatible is False
    codes = {item.code for item in result.incompatibilities}
    assert IncompatibilityCode.SCHEMA_ROOT in codes
    assert IncompatibilityCode.OPERATION_VERSION in codes


def test_adapter_incompatibility_is_typed() -> None:
    result = handshake(
        HandshakeRequirements(
            required_adapter_versions=("SupervisorLogicPlatformClient@99",)
        ),
        manifest=DEFAULT_LOGIC_PLATFORM_MANIFEST,
    )
    assert result.compatible is False
    assert result.incompatibilities[0].code is IncompatibilityCode.ADAPTER_VERSION


def test_catalog_root_mismatch_is_typed() -> None:
    result = handshake(
        HandshakeRequirements(required_catalog_root="baguqeera-not-the-real-root"),
        manifest=DEFAULT_LOGIC_PLATFORM_MANIFEST,
    )
    assert result.compatible is False
    assert result.incompatibilities[0].code is IncompatibilityCode.CATALOG_ROOT


def test_require_source_commit_without_provenance_is_typed() -> None:
    manifest = build_logic_platform_manifest(
        package_version="0.2.0",
        include_source_commit=False,
        environ={},
    )
    result = handshake(
        HandshakeRequirements(require_source_commit=True),
        manifest=manifest,
    )
    assert result.compatible is False
    assert (
        result.incompatibilities[0].code
        is IncompatibilityCode.SOURCE_COMMIT_REQUIRED
    )


def test_source_commit_mismatch_is_typed() -> None:
    manifest = build_logic_platform_manifest(
        package_version="0.2.0",
        source_commit="aaa111",
        include_source_commit=True,
        environ={},
    )
    result = handshake(
        HandshakeRequirements(required_source_commit="bbb222"),
        manifest=manifest,
    )
    assert result.compatible is False
    assert (
        result.incompatibilities[0].code
        is IncompatibilityCode.SOURCE_COMMIT_MISMATCH
    )


def test_matching_source_commit_is_optional_success() -> None:
    manifest = build_logic_platform_manifest(
        package_version="0.2.0",
        source_commit="abc123",
        include_source_commit=True,
        environ={},
    )
    result = handshake(
        HandshakeRequirements(
            require_source_commit=True,
            required_source_commit="abc123",
        ),
        manifest=manifest,
    )
    assert result.compatible is True
    assert result.manifest.git_provenance_available is True


def test_compatible_handshake_with_matching_requirements() -> None:
    manifest = DEFAULT_LOGIC_PLATFORM_MANIFEST
    result = handshake(
        HandshakeRequirements(
            required_package_name=PACKAGE_NAME,
            required_interface_versions={
                LOGIC_PLATFORM_MANIFEST_INTERFACE: LOGIC_PLATFORM_MANIFEST_VERSION,
            },
            required_adapter_versions=("SupervisorLogicPlatformClient@1",),
            required_catalog_root=manifest.catalog_root,
            required_catalog_digest=manifest.catalog_digest,
        ),
        manifest=manifest,
    )
    assert result.compatible is True
    assert result.to_dict()["compatible"] is True
    assert result.to_dict()["incompatibilities"] == []


def test_handshake_accepts_mapping_requirements() -> None:
    result = handshake(
        {
            "required_manifest_interface": LOGIC_PLATFORM_MANIFEST_INTERFACE,
            "min_package_version": "0.0.1",
        },
        manifest=build_logic_platform_manifest(
            package_version="0.2.0",
            include_source_commit=False,
        ),
    )
    assert result.compatible is True


# ---------------------------------------------------------------------------
# Fail-closed structural validation
# ---------------------------------------------------------------------------


def test_invalid_catalog_digest_rejected() -> None:
    with pytest.raises(LogicPlatformManifestError, match="sha256"):
        LogicPlatformManifest(
            package_name=PACKAGE_NAME,
            package_version="0.2.0",
            interface_versions={
                LOGIC_PLATFORM_MANIFEST_INTERFACE: LOGIC_PLATFORM_MANIFEST_VERSION,
            },
            catalog_root="bafytest",
            catalog_digest="not-a-digest",
            schema_roots={},
            operation_versions={},
            receipt_versions={},
            plan_versions={},
            compatible_adapter_versions=(),
        )


def test_compatible_result_cannot_carry_findings() -> None:
    finding = ManifestIncompatibility(
        code=IncompatibilityCode.PACKAGE_VERSION,
        field="package_version",
        expected="1.0.0",
        actual="0.1.0",
        message="too old",
    )
    with pytest.raises(LogicPlatformManifestError, match="compatible"):
        HandshakeResult(
            compatible=True,
            manifest=DEFAULT_LOGIC_PLATFORM_MANIFEST,
            incompatibilities=(finding,),
        )


def test_incompatible_result_requires_findings() -> None:
    with pytest.raises(LogicPlatformManifestError, match="incompatibility"):
        HandshakeResult(
            compatible=False,
            manifest=DEFAULT_LOGIC_PLATFORM_MANIFEST,
            incompatibilities=(),
        )


def test_duplicate_adapter_versions_rejected() -> None:
    with pytest.raises(LogicPlatformManifestError, match="duplicate"):
        build_logic_platform_manifest(
            package_version="0.2.0",
            compatible_adapter_versions=(
                "SupervisorLogicPlatformClient@1",
                "SupervisorLogicPlatformClient@1",
            ),
            include_source_commit=False,
        )


def test_repository_layout_is_not_compatibility_authority() -> None:
    """Semantic compatibility uses declared maps, not checkout adjacency."""

    manifest = build_logic_platform_manifest(
        package_version="0.2.0",
        include_source_commit=False,
        environ={},
    )
    # Even with zero Git provenance and no layout claims, default handshake
    # remains compatible — layout is not consulted.
    assert manifest.requires_repository_layout() is False
    assert handshake(manifest=manifest).compatible is True
    payload = manifest.to_dict()
    assert "sibling" not in payload["notes"].lower() or "without sibling" in payload["notes"]
