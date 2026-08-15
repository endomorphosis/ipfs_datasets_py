"""Internal logic platform surfaces (package-neutral, side-effect free).

Public facades continue to live at ``logic.verification_api`` and related
entry points.  Modules under ``logic.platform`` are the internal composition
and handshake surfaces used by the supervisor client and packaging lanes.
"""

from __future__ import annotations

from ipfs_datasets_py.logic.platform.manifest import (
    DEFAULT_LOGIC_PLATFORM_MANIFEST,
    HANDSHAKE_RESULT_SCHEMA,
    LOGIC_PLATFORM_MANIFEST_INTERFACE,
    LOGIC_PLATFORM_MANIFEST_SCHEMA,
    LOGIC_PLATFORM_MANIFEST_VERSION,
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

__all__ = [
    "DEFAULT_LOGIC_PLATFORM_MANIFEST",
    "HANDSHAKE_RESULT_SCHEMA",
    "LOGIC_PLATFORM_MANIFEST_INTERFACE",
    "LOGIC_PLATFORM_MANIFEST_SCHEMA",
    "LOGIC_PLATFORM_MANIFEST_VERSION",
    "HandshakeRequirements",
    "HandshakeResult",
    "IncompatibilityCode",
    "LogicPlatformManifest",
    "LogicPlatformManifestError",
    "ManifestIncompatibility",
    "build_logic_platform_manifest",
    "handshake",
    "optional_source_commit",
    "resolve_package_version",
]
