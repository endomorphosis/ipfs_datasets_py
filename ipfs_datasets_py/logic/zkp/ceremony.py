"""Shared MCP++ Groth16 multi-party ceremony manifest validation.

This validates participant quorum, signed contribution attestations, artifact
continuity, and the evidence required to admit a key in production. It does
not pretend that deterministic setup or a coordinator-visible seed is an MPC
ceremony. Cryptographic transcript verification remains the responsibility of
the declared ``transcript_verifier`` before finalization.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


MCPPP_GROTH16_MPC_CEREMONY_SCHEMA = "mcp++/groth16-mpc-ceremony@1"
MCPPP_PROFILE_F_NAME = "Profile F: Event DAG Provenance, Archival, and Compaction"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DID_RE = re.compile(r"^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$")


@dataclass(frozen=True)
class CeremonyValidation:
    valid: bool
    production_eligible: bool
    ceremony_cid: str
    independent_contributors: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "production_eligible": self.production_eligible,
            "ceremony_cid": self.ceremony_cid,
            "independent_contributors": list(self.independent_contributors),
            "reasons": list(self.reasons),
        }


def ceremony_cid(manifest: Mapping[str, Any]) -> str:
    """Return the deterministic content identifier for a ceremony manifest."""
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_groth16_mpc_ceremony(manifest: Mapping[str, Any]) -> CeremonyValidation:
    """Validate the common SwissKnife/ipfs_datasets ceremony contract."""
    reasons: list[str] = []
    if manifest.get("schema") != MCPPP_GROTH16_MPC_CEREMONY_SCHEMA:
        reasons.append("unsupported_schema")
    profile = manifest.get("profile")
    if not isinstance(profile, Mapping) or profile.get("capability") != "mcp++/event-dag" or profile.get("name") != MCPPP_PROFILE_F_NAME:
        reasons.append("invalid_profile_f_identity")
    if not isinstance(manifest.get("ceremonyId"), str) or not manifest["ceremonyId"]:
        reasons.append("missing_ceremony_id")
    if not isinstance(manifest.get("circuitId"), str) or not manifest["circuitId"]:
        reasons.append("missing_circuit_id")
    if manifest.get("keyFormat") is not None and manifest.get("keyFormat") not in {"snarkjs-zkey", "arkworks-canonical"}:
        reasons.append("invalid_key_format")
    if not _valid_artifact(manifest.get("circuitR1cs")):
        reasons.append("invalid_circuit_r1cs")
    if not _valid_artifact(manifest.get("phase1Powers")):
        reasons.append("invalid_phase1_powers")

    minimum = manifest.get("minimumIndependentContributors")
    if not isinstance(minimum, int) or minimum < 2:
        reasons.append("minimum_independent_contributors_must_be_at_least_two")
        minimum = 2

    contributions = manifest.get("contributions")
    if not isinstance(contributions, list):
        reasons.append("invalid_contributions")
        contributions = []

    initial_zkey = manifest.get("initialZkey")
    if initial_zkey is not None and not _valid_artifact(initial_zkey):
        reasons.append("invalid_initial_zkey")
    if manifest.get("provingKey") is not None and not _valid_artifact(manifest.get("provingKey")):
        reasons.append("invalid_proving_key")
    if contributions and initial_zkey is None:
        reasons.append("missing_initial_zkey")

    participants: set[str] = set()
    previous_output: str | None = initial_zkey.get("sha256") if isinstance(initial_zkey, Mapping) else None
    for index, contribution in enumerate(contributions, start=1):
        if not isinstance(contribution, Mapping):
            reasons.append(f"invalid_contribution_{index}")
            continue
        if contribution.get("sequence") != index:
            reasons.append(f"invalid_sequence_{index}")
        did = contribution.get("participantDid")
        if not isinstance(did, str) or not _DID_RE.fullmatch(did):
            reasons.append(f"invalid_participant_did_{index}")
        else:
            participants.add(did)
        input_hash = contribution.get("inputArtifactSha256")
        output_hash = contribution.get("outputArtifactSha256")
        if not _valid_sha256(input_hash) or not _valid_sha256(output_hash):
            reasons.append(f"invalid_contribution_hash_{index}")
        if previous_output and input_hash != previous_output:
            reasons.append(f"broken_artifact_chain_{index}")
        if isinstance(output_hash, str):
            previous_output = output_hash
        attestation = contribution.get("attestation")
        if not isinstance(attestation, Mapping) or not all(isinstance(attestation.get(key), str) and attestation[key] for key in ("algorithm", "signature", "signedAt", "statementCid")):
            reasons.append(f"missing_signed_attestation_{index}")
        if contribution.get("transcriptVerifier") not in {"snarkjs-zkey-verify", "arkworks-mpc-verifier"} or not contribution.get("transcriptVerifiedAt"):
            reasons.append(f"missing_transcript_verification_{index}")

    status = manifest.get("status")
    final_zkey = manifest.get("finalZkey")
    verification_key = manifest.get("verificationKey")
    complete = (
        status == "complete"
        and bool(contributions)
        and _valid_artifact(initial_zkey)
        and _valid_artifact(final_zkey)
        and _valid_artifact(verification_key)
        and isinstance(manifest.get("finalizedAt"), str)
        and bool(manifest["finalizedAt"])
        and isinstance(final_zkey, Mapping)
        and final_zkey.get("sha256") == previous_output
    )
    if status == "complete" and not complete:
        reasons.append("incomplete_finalization")

    independent = tuple(sorted(participants))
    production_eligible = not reasons and complete and len(independent) >= minimum
    if not reasons and not production_eligible:
        reasons.append("independent_contributor_quorum_not_met")

    return CeremonyValidation(
        valid=not reasons or reasons == ["independent_contributor_quorum_not_met"],
        production_eligible=production_eligible,
        ceremony_cid=ceremony_cid(manifest),
        independent_contributors=independent,
        reasons=tuple(reasons),
    )


def assert_production_eligible_groth16_ceremony(manifest: Mapping[str, Any]) -> CeremonyValidation:
    result = validate_groth16_mpc_ceremony(manifest)
    if not result.production_eligible:
        raise ValueError(f"Groth16 ceremony is not production eligible: {', '.join(result.reasons) or 'unknown'}")
    return result


def assert_arkworks_mpc_ceremony(
    manifest: Mapping[str, Any],
    *,
    expected_circuit_id: str,
    proving_key_path: str | Path,
    verifying_key_path: str | Path,
) -> CeremonyValidation:
    """Admit an externally generated Arkworks MPC ceremony for local proof use.

    The common MCP++ manifest validates quorum and artifact continuity.  This
    backend-specific gate additionally proves that the manifest describes the
    exact local Arkworks proving and verification keys and an Arkworks
    transcript verifier.
    It intentionally cannot turn this repository's single-RNG ``setup``
    command into a multi-party ceremony.
    """
    result = assert_production_eligible_groth16_ceremony(manifest)
    if manifest.get("keyFormat") != "arkworks-canonical":
        raise ValueError("Arkworks ceremony must declare keyFormat arkworks-canonical")
    if manifest.get("circuitId") != expected_circuit_id:
        raise ValueError(
            "Arkworks ceremony circuitId does not match the requested circuit: "
            f"expected {expected_circuit_id!r}"
        )

    contributions = manifest.get("contributions")
    if not isinstance(contributions, list) or any(
        not isinstance(contribution, Mapping)
        or contribution.get("transcriptVerifier") != "arkworks-mpc-verifier"
        for contribution in contributions
    ):
        raise ValueError("Arkworks ceremony requires arkworks-mpc-verifier evidence for every contribution")
    final_zkey = manifest.get("finalZkey")
    proving_key = manifest.get("provingKey")
    if not isinstance(final_zkey, Mapping) or not isinstance(proving_key, Mapping) or final_zkey.get("sha256") != proving_key.get("sha256"):
        raise ValueError("Arkworks ceremony finalZkey must match the provingKey artifact")

    _assert_local_artifact_hash(
        proving_key,
        proving_key_path,
        artifact_name="provingKey",
    )
    _assert_local_artifact_hash(
        manifest.get("verificationKey"),
        verifying_key_path,
        artifact_name="verificationKey",
    )
    return result


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _valid_artifact(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and _valid_sha256(value.get("sha256"))
        and isinstance(value.get("cid"), str)
        and bool(_CID_RE.fullmatch(value["cid"]))
        and value["cid"] == f"sha256:{value['sha256']}"
        and isinstance(value.get("sizeBytes"), int)
        and value["sizeBytes"] > 0
    )


def _assert_local_artifact_hash(value: Any, path: str | Path, *, artifact_name: str) -> None:
    if not _valid_artifact(value):
        raise ValueError(f"Arkworks ceremony requires a valid {artifact_name} artifact")
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise ValueError(f"Arkworks {artifact_name} is unavailable: {artifact_path}")
    actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if value["sha256"] != actual_hash:
        raise ValueError(f"Arkworks ceremony {artifact_name} hash does not match the local artifact")


__all__ = [
    "MCPPP_GROTH16_MPC_CEREMONY_SCHEMA",
    "MCPPP_PROFILE_F_NAME",
    "CeremonyValidation",
    "assert_arkworks_mpc_ceremony",
    "assert_production_eligible_groth16_ceremony",
    "ceremony_cid",
    "validate_groth16_mpc_ceremony",
]
