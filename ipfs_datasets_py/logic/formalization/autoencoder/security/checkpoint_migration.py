"""Explicit inert-package migration from the qualified supervisor implementation.

Only the two installed implementation bindings and release inventory change.
Weights, training lineage, model card, native manifest and numerical fixtures
remain byte-identical. This never upgrades training quality or proof authority.
"""
from pathlib import Path
import tempfile

from . import security_autoencoder_checkpoint as checkpoint
from .security_autoencoder_hub import _manifest

# Exactly the implementation pair used by the retained development release.
# Unknown or partially matching producers require a separate migration review.
LEGACY_IMPLEMENTATIONS = {
    "inference_implementation_sha256": "f1f13654313e54bae6af44bf2736ce57768937a4764a9cd95a5084469c36f0d0",
    "feature_implementation_sha256": "6304391b4dc2741ce999c0e8d5d489fdb553cf85ca68df17b16381a29ac05164",
}


def migrate_supervisor_security_checkpoint(*, package: Path,
        expected_manifest_sha256: str, output: Path) -> dict:
    """Rebind a pinned legacy package, replay it, then atomically publish locally."""
    package = checkpoint._namespace(Path(package))
    output = checkpoint._namespace(Path(output), fresh=True, excluded=(package,))
    if output in package.parents or set(p.name for p in package.iterdir()) != checkpoint.PACKAGE_FILES:
        raise ValueError("closed separate migration namespaces required")
    raw_manifest = checkpoint._read(package / "release-manifest.json", 32_768)
    manifest = _manifest(raw_manifest, expected_manifest_sha256)
    original = {"release-manifest.json": raw_manifest}
    total = len(raw_manifest)
    for name, entry in manifest["files"].items():
        raw = checkpoint._read(package / name)
        total += len(raw)
        if (len(raw) != entry["bytes"] or checkpoint._sha(raw) != entry["sha256"]
                or total > checkpoint.MAX_BYTES):
            raise ValueError("legacy migration payload binding differs")
        original[name] = raw
    config = checkpoint._decode(original["config.json"])
    if any(config.get(key) != value for key, value in LEGACY_IMPLEMENTATIONS.items()):
        raise ValueError("unreviewed legacy implementation pair")
    current = checkpoint._config(config.get("latent_width"))
    migrated_config = {**config, **{key: current[key] for key in LEGACY_IMPLEMENTATIONS}}
    if not checkpoint._numerically_equal(migrated_config, current):
        raise ValueError("legacy inference semantics differ from the reviewed migration")
    migrated = {**original, "config.json": checkpoint._json(migrated_config)}
    manifest["files"] = {name: {"sha256": checkpoint._sha(raw), "bytes": len(raw)}
                         for name, raw in migrated.items() if name != "release-manifest.json"}
    migrated["release-manifest.json"] = checkpoint._json(manifest)
    digest = checkpoint._sha(migrated["release-manifest.json"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".security-migration-", dir=output.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()
        for name, raw in migrated.items():
            checkpoint._write(stage / name, raw)
        # Full closed-schema, lineage, native-manifest and numerical replay.
        checkpoint.load_security_checkpoint(stage, expected_manifest_sha256=digest)
        if any(checkpoint._read(package / name) != raw for name, raw in original.items()):
            raise ValueError("legacy package changed during migration")
        if output.exists():
            raise ValueError("migration output appeared during validation")
        stage.rename(output)
    loaded = checkpoint.load_security_checkpoint(output, expected_manifest_sha256=digest)
    return {"schema": "security-autoencoder-owner-migration@1",
        "source_manifest_sha256": expected_manifest_sha256,
        "destination": loaded["descriptor"],
        "producer_implementation": LEGACY_IMPLEMENTATIONS,
        "consumer_implementation": {key: current[key] for key in LEGACY_IMPLEMENTATIONS},
        "unchanged_files": sorted(checkpoint.PACKAGE_FILES - {"config.json", "release-manifest.json"}),
        "checkpoint_sha256": checkpoint._sha(original["checkpoint.json"]),
        "numeric_fixture_replayed": True, "source_modified": False,
        "training_steps": 0, "provider_calls": 0, "download_calls": 0,
        "checkpoint_uploaded": False, "runtime_promoted": False,
        "proof_authority": False, "formalization_authority": False}
