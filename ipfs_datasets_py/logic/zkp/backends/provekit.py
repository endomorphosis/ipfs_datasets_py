"""ProveKit backend entrypoint.

This module registers a fail-closed backend shell for World Foundation
ProveKit. It is intentionally lightweight: selecting the backend does not
discover binaries, build Rust code, prepare keys, or touch proof artifacts.

Actual proving and verification require:

- a configured ``provekit-cli`` binary,
- prepared ProveKit key artifacts,
- explicit witness/proof paths supplied by later integration layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Mapping, Optional

from .. import ZKPError, ZKPProof
from ..circuits import build_proof_attestation_view
from ..provekit.cli import ProveKitCLI, discover_provekit_binary
from ..provekit.public_inputs import build_provekit_public_input_record


@dataclass
class ProveKitBackend:
    """World Foundation ProveKit WHIR backend shell.

    The backend is selectable through ``get_backend("provekit")`` but fails
    closed until a caller supplies real ProveKit artifacts. This prevents silent
    fallback to simulated proofs.
    """

    backend_id: str = "provekit"
    proof_system: str = "ProveKit-WHIR"
    curve_id: str = "bn254"
    timeout_seconds: float = 60.0
    binary_path: Optional[str] = None

    def binary_available(self) -> bool:
        """Return True if a ProveKit CLI binary is configured/discoverable."""

        try:
            if self.binary_path:
                ProveKitCLI(
                    binary_path=self.binary_path,
                    timeout_seconds=self.timeout_seconds,
                )
                return True
            return discover_provekit_binary() is not None
        except ZKPError:
            return False

    def generate_proof(
        self,
        theorem: str,
        private_axioms: list[str],
        metadata: dict[str, Any],
    ) -> ZKPProof:
        """Generate a ProveKit proof from already prepared artifacts.

        This skeleton expects later tasks to render the private witness file and
        artifact manifest. If those paths are absent, it raises ``ZKPError``.
        """

        if not theorem:
            raise ZKPError("Theorem cannot be empty")
        if not private_axioms:
            raise ZKPError("At least one axiom required")

        metadata_dict = dict(metadata or {})
        cli = self._cli_or_raise()
        artifacts = _artifact_mapping(metadata_dict)
        prover_key = _required_existing_path(
            artifacts,
            "prover_key_path",
            "pkp_path",
            label="prover key",
        )
        input_path = _required_existing_path(
            artifacts,
            "input_path",
            "prover_toml_path",
            label="private Prover.toml input",
        )
        proof_path = _required_output_path(
            artifacts,
            "proof_path",
            "proof_output_path",
            label="proof output",
        )

        result = cli.prove(
            prover_key_path=prover_key,
            input_path=input_path,
            proof_path=proof_path,
            cwd=_optional_path(artifacts, "cwd", "program_dir", "package_dir"),
            extra_sensitive_values=tuple(private_axioms),
        )
        if not result.ok:
            raise ZKPError(f"ProveKit proof generation failed: {result.to_dict()}")
        if not proof_path.is_file():
            raise ZKPError(f"ProveKit proof output was not created: {proof_path}")

        proof_data = proof_path.read_bytes()
        record = build_provekit_public_input_record(
            theorem=theorem,
            private_axioms=private_axioms,
            metadata=metadata_dict,
        ).with_attestation(
            proof_data=proof_data,
            metadata={
                **metadata_dict,
                "backend": self.backend_id,
                "proof_system": self.proof_system,
            },
        )

        public_inputs = record.to_zkp_public_inputs()
        attestation_metadata = {
            **metadata_dict,
            "backend": self.backend_id,
            "proof_system": self.proof_system,
        }
        attestation_view = build_proof_attestation_view(
            proof_data=proof_data,
            public_inputs=public_inputs,
            metadata=attestation_metadata,
        )
        public_inputs["attestation_ref"] = attestation_view["attestation_ref"]
        public_inputs["attestation_view_version"] = int(
            attestation_view["attestation_view_version"]
        )
        output_metadata = {
            **metadata_dict,
            "backend": self.backend_id,
            "proof_system": self.proof_system,
            "curve_id": self.curve_id,
            "attestation_view": attestation_view,
            "provekit": {
                "binary_path": str(cli.binary_path),
                "command": result.to_dict(),
                "artifacts": _public_artifact_record(artifacts),
                "public_input_schema": record.schema_version,
                "public_input_hash": record.canonical_hash(),
            },
        }
        output_metadata.setdefault(
            "security_level",
            int(metadata_dict.get("security_level", 128)),
        )

        return ZKPProof(
            proof_data=proof_data,
            public_inputs=public_inputs,
            metadata=output_metadata,
            timestamp=time.time(),
            size_bytes=len(proof_data),
        )

    def verify_proof(self, proof: ZKPProof) -> bool:
        """Verify a ProveKit proof using explicit verifier artifacts."""

        cli = self._cli_or_raise()
        metadata = getattr(proof, "metadata", None)
        if not isinstance(metadata, dict):
            raise ZKPError("ProveKit proof metadata must contain artifact paths")

        artifacts = _artifact_mapping(metadata)
        verifier_key = _required_existing_path(
            artifacts,
            "verifier_key_path",
            "pkv_path",
            label="verifier key",
        )
        proof_path = _required_existing_path(
            artifacts,
            "proof_path",
            "proof_output_path",
            label="proof file",
        )

        result = cli.verify(
            verifier_key_path=verifier_key,
            proof_path=proof_path,
            cwd=_optional_path(artifacts, "cwd", "program_dir", "package_dir"),
        )
        if not result.ok:
            raise ZKPError(f"ProveKit proof verification failed: {result.to_dict()}")
        return True

    def get_backend_info(self) -> dict[str, Any]:
        """Return a lightweight backend readiness summary."""

        binary_path: Optional[str] = None
        try:
            if self.binary_path:
                binary_path = str(ProveKitCLI(binary_path=self.binary_path).binary_path)
            else:
                discovered = discover_provekit_binary()
                binary_path = str(discovered) if discovered else None
        except ZKPError:
            binary_path = None

        return {
            "backend_id": self.backend_id,
            "proof_system": self.proof_system,
            "curve_id": self.curve_id,
            "binary_path": binary_path,
            "binary_available": binary_path is not None,
            "timeout_seconds": self.timeout_seconds,
            "requires_artifacts": True,
        }

    def _cli_or_raise(self) -> ProveKitCLI:
        try:
            return ProveKitCLI(
                binary_path=self.binary_path,
                timeout_seconds=self.timeout_seconds,
            )
        except ZKPError as exc:
            raise ZKPError(
                "ProveKit backend is unavailable: configure a provekit-cli "
                "binary with IPFS_DATASETS_PROVEKIT_CLI or "
                f"IPFS_DATASETS_PROVEKIT_HOME. Original error: {exc}"
            ) from exc


def _artifact_mapping(metadata: Mapping[str, Any]) -> dict[str, Any]:
    nested = metadata.get("provekit_artifacts")
    if isinstance(nested, Mapping):
        artifacts = dict(nested)
    else:
        artifacts = {}
    for key in (
        "prover_key_path",
        "pkp_path",
        "verifier_key_path",
        "pkv_path",
        "input_path",
        "prover_toml_path",
        "proof_path",
        "proof_output_path",
        "cwd",
        "program_dir",
        "package_dir",
    ):
        if key in metadata and key not in artifacts:
            artifacts[key] = metadata[key]
    if not artifacts:
        raise ZKPError(
            "ProveKit backend requires explicit artifact metadata under "
            "metadata['provekit_artifacts']"
        )
    return artifacts


def _optional_path(artifacts: Mapping[str, Any], *keys: str) -> Optional[Path]:
    for key in keys:
        value = artifacts.get(key)
        if value:
            return Path(str(value))
    return None


def _required_existing_path(
    artifacts: Mapping[str, Any],
    *keys: str,
    label: str,
) -> Path:
    path = _optional_path(artifacts, *keys)
    if path is None:
        raise ZKPError(f"ProveKit backend requires {label} artifact metadata")
    if not path.is_file():
        raise ZKPError(f"ProveKit {label} artifact is missing: {path}")
    return path


def _required_output_path(
    artifacts: Mapping[str, Any],
    *keys: str,
    label: str,
) -> Path:
    path = _optional_path(artifacts, *keys)
    if path is None:
        raise ZKPError(f"ProveKit backend requires {label} artifact metadata")
    parent = path.parent
    if parent and not parent.exists():
        raise ZKPError(f"ProveKit {label} directory is missing: {parent}")
    return path


def _public_artifact_record(artifacts: Mapping[str, Any]) -> dict[str, str]:
    """Return non-secret artifact path metadata for proof envelopes."""

    public: dict[str, str] = {}
    for key in (
        "prover_key_path",
        "pkp_path",
        "verifier_key_path",
        "pkv_path",
        "proof_path",
        "proof_output_path",
        "program_dir",
        "package_dir",
    ):
        value = artifacts.get(key)
        if value:
            public[key] = str(value)
    return public


__all__ = ["ProveKitBackend"]
