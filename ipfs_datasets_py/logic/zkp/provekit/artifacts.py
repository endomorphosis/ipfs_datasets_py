"""Artifact manifests for ProveKit-backed ZKP circuits.

The manifest is intentionally deterministic and stdlib-only. It records local
paths and SHA-256 digests for a prepared ProveKit circuit package and its
prover/verifier keys. Validation fails closed when required files are missing or
when current digests differ from the manifest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from .. import ZKPError
from ..statement import format_circuit_ref, parse_circuit_ref_lenient
from .public_inputs import (
    DEFAULT_PROVEKIT_CIRCUIT_VERSION,
    DEFAULT_PROVEKIT_HASH_BACKEND,
    DEFAULT_PROVEKIT_RULESET_ID,
)


PROVEKIT_ARTIFACT_MANIFEST_SCHEMA_VERSION = "provekit-artifact-manifest-v1"
DEFAULT_PROVEKIT_MANIFEST_FILENAME = "provekit-artifacts.json"


@dataclass(frozen=True)
class ProveKitKeyPair:
    """Prepared ProveKit prover/verifier key paths."""

    prover_key_path: str
    verifier_key_path: str

    @classmethod
    def from_paths(cls, prover_key_path: str | Path, verifier_key_path: str | Path) -> "ProveKitKeyPair":
        return cls(
            prover_key_path=str(Path(prover_key_path).resolve()),
            verifier_key_path=str(Path(verifier_key_path).resolve()),
        )


@dataclass(frozen=True)
class ProveKitArtifactManifest:
    """Deterministic manifest for a prepared ProveKit circuit."""

    circuit_id: str
    circuit_version: int
    circuit_ref: str
    ruleset_id: str
    hash_backend: str
    noir_package_path: str
    prover_key_path: str
    verifier_key_path: str
    provekit_branch: str
    provekit_commit: str
    noir_package_sha256: str
    prover_key_sha256: str
    verifier_key_sha256: str
    schema_version: str = PROVEKIT_ARTIFACT_MANIFEST_SCHEMA_VERSION
    provekit_binary_path: str = ""
    provekit_binary_sha256: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != PROVEKIT_ARTIFACT_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported ProveKit artifact manifest schema_version")
        if not isinstance(self.circuit_id, str) or not self.circuit_id or "@" in self.circuit_id:
            raise ValueError("circuit_id must be a non-empty unversioned string")
        if not isinstance(self.circuit_version, int) or self.circuit_version < 0:
            raise ValueError("circuit_version must be a non-negative integer")
        parsed_id, parsed_version = parse_circuit_ref_lenient(
            self.circuit_ref,
            legacy_default_version=self.circuit_version,
        )
        if parsed_id != self.circuit_id or parsed_version != self.circuit_version:
            raise ValueError("circuit_ref must match circuit_id and circuit_version")
        if self.circuit_ref != format_circuit_ref(self.circuit_id, self.circuit_version):
            raise ValueError("circuit_ref must be canonical")
        for field_name in ("ruleset_id", "hash_backend", "provekit_branch", "provekit_commit"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name):
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in (
            "noir_package_sha256",
            "prover_key_sha256",
            "verifier_key_sha256",
        ):
            _validate_sha256_hex(field_name, getattr(self, field_name))
        if self.provekit_binary_sha256:
            _validate_sha256_hex("provekit_binary_sha256", self.provekit_binary_sha256)
        elif self.provekit_binary_path:
            raise ValueError("provekit_binary_sha256 is required when provekit_binary_path is set")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable manifest dictionary."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProveKitArtifactManifest":
        """Build a manifest from a dictionary."""

        if not isinstance(data, Mapping):
            raise TypeError("manifest data must be a mapping")
        return cls(**dict(data))

    def canonical_json(self) -> str:
        """Return deterministic compact JSON for signing/cache keys."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def manifest_sha256(self) -> str:
        """Return SHA-256 over the deterministic manifest JSON."""

        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def validate_files(self) -> None:
        """Validate all manifest paths and digests, failing closed on mismatch."""

        _validate_existing_digest(
            Path(self.noir_package_path),
            self.noir_package_sha256,
            label="Noir package",
            directory=True,
        )
        _validate_existing_digest(
            Path(self.prover_key_path),
            self.prover_key_sha256,
            label="ProveKit prover key",
        )
        _validate_existing_digest(
            Path(self.verifier_key_path),
            self.verifier_key_sha256,
            label="ProveKit verifier key",
        )
        if self.provekit_binary_path:
            _validate_existing_digest(
                Path(self.provekit_binary_path),
                self.provekit_binary_sha256,
                label="ProveKit binary",
            )

    def to_backend_artifacts(self) -> dict[str, Any]:
        """Return metadata accepted by ``ProveKitBackend``."""

        return {
            "provekit_artifacts": {
                "program_dir": self.noir_package_path,
                "prover_key_path": self.prover_key_path,
                "verifier_key_path": self.verifier_key_path,
                "hash_backend": self.hash_backend,
                "provekit_branch": self.provekit_branch,
                "provekit_commit": self.provekit_commit,
                "manifest_sha256": self.manifest_sha256(),
                "manifest_schema_version": self.schema_version,
            }
        }


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 for a file."""

    file_path = Path(path)
    if not file_path.is_file():
        raise ZKPError(f"file does not exist: {file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(
    path: str | Path,
    *,
    exclude_dirs: Sequence[str] = ("target", ".git", "__pycache__"),
    exclude_suffixes: Sequence[str] = (".pkp", ".pkv", ".np", ".pyc"),
) -> str:
    """Return deterministic SHA-256 for file contents under a directory."""

    root = Path(path)
    if not root.is_dir():
        raise ZKPError(f"directory does not exist: {root}")

    digest = hashlib.sha256()
    files = sorted(_iter_manifest_files(root, exclude_dirs, exclude_suffixes))
    for file_path in files:
        relative = file_path.relative_to(root).as_posix()
        payload = file_path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def build_provekit_artifact_manifest(
    *,
    circuit_id: str,
    noir_package_path: str | Path,
    prover_key_path: str | Path,
    verifier_key_path: str | Path,
    provekit_branch: str,
    provekit_commit: str,
    circuit_version: int = DEFAULT_PROVEKIT_CIRCUIT_VERSION,
    ruleset_id: str = DEFAULT_PROVEKIT_RULESET_ID,
    hash_backend: str = DEFAULT_PROVEKIT_HASH_BACKEND,
    provekit_binary_path: Optional[str | Path] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> ProveKitArtifactManifest:
    """Create a manifest by hashing current package/key files."""

    package = Path(noir_package_path).resolve()
    prover_key = Path(prover_key_path).resolve()
    verifier_key = Path(verifier_key_path).resolve()
    binary = Path(provekit_binary_path).resolve() if provekit_binary_path else None

    return ProveKitArtifactManifest(
        circuit_id=circuit_id,
        circuit_version=circuit_version,
        circuit_ref=format_circuit_ref(circuit_id, circuit_version),
        ruleset_id=ruleset_id,
        hash_backend=hash_backend,
        noir_package_path=str(package),
        prover_key_path=str(prover_key),
        verifier_key_path=str(verifier_key),
        provekit_branch=provekit_branch,
        provekit_commit=provekit_commit,
        noir_package_sha256=sha256_directory(package),
        prover_key_sha256=sha256_file(prover_key),
        verifier_key_sha256=sha256_file(verifier_key),
        provekit_binary_path=str(binary) if binary else "",
        provekit_binary_sha256=sha256_file(binary) if binary else "",
        metadata=dict(metadata or {}),
    )


def find_provekit_key_pair(
    search_root: str | Path,
    *,
    circuit_id: str,
    circuit_version: int = DEFAULT_PROVEKIT_CIRCUIT_VERSION,
) -> Optional[ProveKitKeyPair]:
    """Find a prepared ``.pkp``/``.pkv`` pair under ``search_root``.

    Matching prefers stems derived from ``circuit_id`` and ``circuit_version``.
    If multiple matching pairs exist, the function fails closed instead of
    guessing. If no matching pair exists, ``None`` is returned.
    """

    root = Path(search_root)
    if not root.exists():
        raise ZKPError(f"ProveKit artifact search root does not exist: {root}")

    preferred_stems = (
        circuit_id,
        f"{circuit_id}_v{circuit_version}",
        f"{circuit_id}@v{circuit_version}",
    )
    pairs: list[tuple[int, Path, Path]] = []
    for pkp_path in sorted(root.rglob("*.pkp")):
        pkv_path = pkp_path.with_suffix(".pkv")
        if not pkv_path.is_file():
            continue
        if pkp_path.stem not in preferred_stems:
            continue
        pairs.append((preferred_stems.index(pkp_path.stem), pkp_path, pkv_path))

    if not pairs:
        return None
    pairs.sort(key=lambda item: (item[0], str(item[1])))
    best_priority = pairs[0][0]
    best = [pair for pair in pairs if pair[0] == best_priority]
    if len(best) > 1:
        choices = ", ".join(str(pair[1]) for pair in best)
        raise ZKPError(f"Ambiguous ProveKit key pairs for {circuit_id}: {choices}")
    _, pkp_path, pkv_path = best[0]
    return ProveKitKeyPair.from_paths(pkp_path, pkv_path)


def save_provekit_artifact_manifest(
    manifest: ProveKitArtifactManifest,
    path: str | Path,
) -> Path:
    """Write a manifest to disk as deterministic pretty JSON."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return out_path


def load_provekit_artifact_manifest(
    path: str | Path,
    *,
    validate_files: bool = True,
) -> ProveKitArtifactManifest:
    """Load a manifest JSON file and optionally validate file digests."""

    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ZKPError(f"ProveKit artifact manifest does not exist: {manifest_path}")
    manifest = ProveKitArtifactManifest.from_dict(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    if validate_files:
        manifest.validate_files()
    return manifest


def _iter_manifest_files(
    root: Path,
    exclude_dirs: Sequence[str],
    exclude_suffixes: Sequence[str],
) -> Iterable[Path]:
    excluded_dirs = set(exclude_dirs)
    excluded_suffixes = set(exclude_suffixes)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in excluded_dirs for part in relative_parts[:-1]):
            continue
        if path.suffix in excluded_suffixes:
            continue
        yield path


def _validate_existing_digest(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
    directory: bool = False,
) -> None:
    if directory:
        actual = sha256_directory(path)
    else:
        actual = sha256_file(path)
    if actual != expected_sha256:
        raise ZKPError(
            f"{label} digest mismatch for {path}: expected {expected_sha256}, got {actual}"
        )


def _validate_sha256_hex(field_name: str, value: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be 64 lowercase hex characters")
    if value.lower() != value:
        raise ValueError(f"{field_name} must be lowercase hex")
    try:
        int(value, 16)
    except Exception as exc:
        raise ValueError(f"{field_name} must be hex") from exc


__all__ = [
    "DEFAULT_PROVEKIT_MANIFEST_FILENAME",
    "PROVEKIT_ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "ProveKitArtifactManifest",
    "ProveKitKeyPair",
    "build_provekit_artifact_manifest",
    "find_provekit_key_pair",
    "load_provekit_artifact_manifest",
    "save_provekit_artifact_manifest",
    "sha256_directory",
    "sha256_file",
]

