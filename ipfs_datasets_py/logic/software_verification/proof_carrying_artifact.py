"""Independent proof-carrying artifact bundle and verifier (LGCVF-090).

The bundle stores *references* to exact semantic, contract, abstract, proof,
test, static, security, policy, and authority lineage.  It does not carry
proof bodies, source, or producer pass-flags as correctness.  The verifier
rebuilds content identities and compact checks from the payload and rejects
forged CIDs, stale roots, missing mandatory evidence, and producer flags.

This module reuses the software-contract CID profile.  It does not create a
generic receipt hierarchy or grant semantic/proof/write authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    ContentIdentityError,
    cid_for_structured,
    validate_cid,
)


PROOF_CARRYING_ARTIFACT_INTERFACE: Final[str] = "ProofCarryingArtifact@1"
PROOF_CARRYING_ARTIFACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/software-verification/proof-carrying-artifact@1"
)
PROOF_CARRYING_VERIFIER_INTERFACE: Final[str] = "ProofCarryingArtifactVerifier@1"
PROOF_CARRYING_VERIFICATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/software-verification/proof-carrying-verification@1"
)
PRODUCER_ID: Final[str] = "proof-carrying-artifact@1"
CONTRACT_VERSION: Final[int] = 1

MANDATORY_LINEAGE_KINDS: Final[tuple[str, ...]] = (
    "semantic",
    "contract",
    "abstract",
    "proof",
    "test",
    "static",
    "security",
    "policy",
    "authority",
)

FORBIDDEN_PRODUCER_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "admitted",
        "complete",
        "completed",
        "completion_authority",
        "ok",
        "pass",
        "producer_pass",
        "producer_verified",
        "production_authorized",
        "release_qualified",
        "self_certified",
        "verified",
    }
)

_COMPACT_CHECK_NAMES: Final[tuple[str, ...]] = (
    "lineage",
    "roots",
)


class ProofCarryingArtifactError(ValueError):
    """Malformed bundle construction input."""


class ProofCarryingArtifactAuthorityError(ProofCarryingArtifactError):
    """The bundle attempted to carry producer or completion authority."""


class ProofCarryingDisposition(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"


class ProofCarryingIssue(StrEnum):
    FORGED_CID = "forged_artifact_cid"
    STALE_ROOT = "stale_root"
    MISSING_MANDATORY_EVIDENCE = "missing_mandatory_evidence"
    PRODUCER_FLAG = "producer_flag"
    MALFORMED_CID = "malformed_lineage_or_root_cid"
    COMPACT_CHECK_MISMATCH = "compact_check_mismatch"
    LINEAGE_MISMATCH = "lineage_mismatch"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise ProofCarryingArtifactError(
            f"{label} must be a nonempty trimmed string without NUL"
        )
    return value


def _cid(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        return validate_cid(text)
    except ContentIdentityError as error:
        raise ProofCarryingArtifactError(f"{label} is not a software-contract CID") from error


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProofCarryingArtifactError(f"{label} must be a mapping")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ProofCarryingArtifactError(f"{label} keys must be nonempty strings")
        result[key] = item
    return result


def _walk_producer_flags(payload: Any, *, path: str = "") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(payload, Mapping):
        for key, item in payload.items():
            next_path = f"{path}.{key}" if path else str(key)
            lowered = str(key).strip().lower()
            if lowered in FORBIDDEN_PRODUCER_FLAGS:
                found.append(next_path)
            found.extend(_walk_producer_flags(item, path=next_path))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for index, item in enumerate(payload):
            found.extend(_walk_producer_flags(item, path=f"{path}[{index}]"))
    return tuple(found)


def _require_no_producer_flags(payload: Any, *, label: str) -> None:
    flags = _walk_producer_flags(payload)
    if flags:
        raise ProofCarryingArtifactAuthorityError(
            f"{label} contains producer flags: {flags[0]}"
        )


@dataclass(frozen=True, slots=True)
class ArtifactLineage:
    """Exact mandatory lineage references; extra refs cannot replace these."""

    semantic_ref: str
    contract_ref: str
    abstract_ref: str
    proof_ref: str
    test_ref: str
    static_ref: str
    security_ref: str
    policy_ref: str
    authority_ref: str
    extra_refs: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for kind in MANDATORY_LINEAGE_KINDS:
            object.__setattr__(self, f"{kind}_ref", _cid(getattr(self, f"{kind}_ref"), f"{kind}_ref"))
        extras = _mapping(self.extra_refs, "extra_refs")
        normalized: dict[str, str] = {}
        for key, value in extras.items():
            if key in MANDATORY_LINEAGE_KINDS:
                raise ProofCarryingArtifactError(
                    "extra_refs cannot override mandatory lineage kinds"
                )
            normalized[_text(key, "extra_refs key")] = _cid(value, f"extra_refs.{key}")
        object.__setattr__(self, "extra_refs", MappingProxyType(normalized))

    def as_mapping(self) -> dict[str, str]:
        payload = {kind: getattr(self, f"{kind}_ref") for kind in MANDATORY_LINEAGE_KINDS}
        payload.update(self.extra_refs)
        return payload

    def missing_kinds(self) -> tuple[str, ...]:
        missing = [
            kind
            for kind in MANDATORY_LINEAGE_KINDS
            if not getattr(self, f"{kind}_ref")
        ]
        return tuple(missing)

    def to_dict(self) -> dict[str, Any]:
        return {
            **{f"{kind}_ref": getattr(self, f"{kind}_ref") for kind in MANDATORY_LINEAGE_KINDS},
            "extra_refs": dict(self.extra_refs),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArtifactLineage":
        if not isinstance(payload, Mapping):
            raise ProofCarryingArtifactError("lineage must be a mapping")
        return cls(
            semantic_ref=str(payload.get("semantic_ref") or ""),
            contract_ref=str(payload.get("contract_ref") or ""),
            abstract_ref=str(payload.get("abstract_ref") or ""),
            proof_ref=str(payload.get("proof_ref") or ""),
            test_ref=str(payload.get("test_ref") or ""),
            static_ref=str(payload.get("static_ref") or ""),
            security_ref=str(payload.get("security_ref") or ""),
            policy_ref=str(payload.get("policy_ref") or ""),
            authority_ref=str(payload.get("authority_ref") or ""),
            extra_refs=_mapping(payload.get("extra_refs"), "extra_refs"),
        )


@dataclass(frozen=True, slots=True)
class ProofCarryingRoots:
    """Current-tree roots bound into the artifact; stale copies fail closed."""

    repository_id: str
    tree_id: str
    semantic_state_root: str
    contract_root: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        object.__setattr__(self, "tree_id", _cid(self.tree_id, "tree_id"))
        object.__setattr__(
            self, "semantic_state_root", _cid(self.semantic_state_root, "semantic_state_root")
        )
        object.__setattr__(self, "contract_root", _cid(self.contract_root, "contract_root"))

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_root": self.contract_root,
            "repository_id": self.repository_id,
            "semantic_state_root": self.semantic_state_root,
            "tree_id": self.tree_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofCarryingRoots":
        if not isinstance(payload, Mapping):
            raise ProofCarryingArtifactError("roots must be a mapping")
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            tree_id=str(payload.get("tree_id") or ""),
            semantic_state_root=str(payload.get("semantic_state_root") or ""),
            contract_root=str(payload.get("contract_root") or ""),
        )


def _compact_checks_for(lineage: ArtifactLineage, roots: ProofCarryingRoots) -> dict[str, str]:
    return {
        "lineage": cid_for_structured(lineage.as_mapping()),
        "roots": cid_for_structured(roots.to_dict()),
    }


def _artifact_preimage(
    *,
    lineage: ArtifactLineage,
    roots: ProofCarryingRoots,
    compact_checks: Mapping[str, str],
    producer_id: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "compact_checks": dict(compact_checks),
        "contract_version": CONTRACT_VERSION,
        "interface": PROOF_CARRYING_ARTIFACT_INTERFACE,
        "lineage": lineage.to_dict(),
        "metadata": dict(metadata),
        "producer_id": producer_id,
        "roots": roots.to_dict(),
        "schema": PROOF_CARRYING_ARTIFACT_SCHEMA,
        "semantic_authority": False,
        "grants_proof_authority": False,
        "grants_write_authority": False,
    }


@dataclass(frozen=True, slots=True)
class ProofCarryingArtifact:
    """Content-addressed proof-carrying bundle. Identity is reconstructed, never trusted."""

    lineage: ArtifactLineage
    roots: ProofCarryingRoots
    compact_checks: Mapping[str, str] = field(default_factory=dict)
    artifact_cid: str = ""
    producer_id: str = PRODUCER_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, ArtifactLineage):
            raise ProofCarryingArtifactError("lineage must be ArtifactLineage")
        if not isinstance(self.roots, ProofCarryingRoots):
            raise ProofCarryingArtifactError("roots must be ProofCarryingRoots")
        object.__setattr__(self, "producer_id", _text(self.producer_id, "producer_id"))
        metadata = MappingProxyType(_mapping(self.metadata, "metadata"))
        _require_no_producer_flags(dict(metadata), label="metadata")
        object.__setattr__(self, "metadata", metadata)
        checks = _mapping(self.compact_checks, "compact_checks")
        normalized_checks = {
            _text(key, "compact_checks key"): _cid(value, f"compact_checks.{key}")
            for key, value in checks.items()
        }
        if not normalized_checks:
            normalized_checks = _compact_checks_for(self.lineage, self.roots)
        object.__setattr__(self, "compact_checks", MappingProxyType(normalized_checks))
        preimage = _artifact_preimage(
            lineage=self.lineage,
            roots=self.roots,
            compact_checks=self.compact_checks,
            producer_id=self.producer_id,
            metadata=self.metadata,
        )
        expected = cid_for_structured(preimage)
        claimed = self.artifact_cid
        if claimed:
            try:
                claimed = validate_cid(claimed)
            except ContentIdentityError as error:
                raise ProofCarryingArtifactError("artifact_cid is not a software-contract CID") from error
        object.__setattr__(self, "artifact_cid", claimed or expected)

    @property
    def reconstructed_cid(self) -> str:
        return cid_for_structured(
            _artifact_preimage(
                lineage=self.lineage,
                roots=self.roots,
                compact_checks=self.compact_checks,
                producer_id=self.producer_id,
                metadata=self.metadata,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        payload = _artifact_preimage(
            lineage=self.lineage,
            roots=self.roots,
            compact_checks=self.compact_checks,
            producer_id=self.producer_id,
            metadata=self.metadata,
        )
        payload["artifact_cid"] = self.artifact_cid
        return payload

    @classmethod
    def build(
        cls,
        *,
        lineage: ArtifactLineage,
        roots: ProofCarryingRoots,
        metadata: Mapping[str, Any] | None = None,
        producer_id: str = PRODUCER_ID,
    ) -> "ProofCarryingArtifact":
        compact = _compact_checks_for(lineage, roots)
        artifact = cls(
            lineage=lineage,
            roots=roots,
            compact_checks=compact,
            producer_id=producer_id,
            metadata=metadata or {},
        )
        object.__setattr__(artifact, "artifact_cid", artifact.reconstructed_cid)
        return artifact

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProofCarryingArtifact":
        if not isinstance(payload, Mapping):
            raise ProofCarryingArtifactError("artifact must be a mapping")
        return cls(
            lineage=ArtifactLineage.from_dict(_mapping(payload.get("lineage"), "lineage")),
            roots=ProofCarryingRoots.from_dict(_mapping(payload.get("roots"), "roots")),
            compact_checks=_mapping(payload.get("compact_checks"), "compact_checks"),
            artifact_cid=str(payload.get("artifact_cid") or ""),
            producer_id=str(payload.get("producer_id") or PRODUCER_ID),
            metadata=_mapping(payload.get("metadata"), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class ProofCarryingVerification:
    """Independent reconstruction receipt. Never a production authorization."""

    disposition: ProofCarryingDisposition
    artifact_cid: str
    replay_receipt_cid: str
    issues: tuple[str, ...] = ()
    checks: Mapping[str, bool] = field(default_factory=dict)
    interface: str = PROOF_CARRYING_VERIFIER_INTERFACE

    @property
    def valid(self) -> bool:
        return self.disposition is ProofCarryingDisposition.VALIDATED and not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_cid": self.artifact_cid,
            "checks": dict(self.checks),
            "disposition": self.disposition.value,
            "interface": self.interface,
            "issues": list(self.issues),
            "replay_receipt_cid": self.replay_receipt_cid,
            "schema": PROOF_CARRYING_VERIFICATION_SCHEMA,
            "valid": self.valid,
            "completion_authority": False,
            "production_authorized": False,
        }


def verify_proof_carrying_artifact(
    artifact: ProofCarryingArtifact | Mapping[str, Any],
    *,
    expected_roots: ProofCarryingRoots | Mapping[str, Any] | None = None,
    expected_lineage: ArtifactLineage | Mapping[str, Any] | None = None,
) -> ProofCarryingVerification:
    """Rebuild identities and compact checks; reject forged/stale/omitted evidence."""

    issues: list[str] = []
    checks: dict[str, bool] = {}

    if isinstance(artifact, Mapping):
        try:
            bundle = ProofCarryingArtifact.from_dict(artifact)
        except ProofCarryingArtifactAuthorityError:
            issues.append(ProofCarryingIssue.PRODUCER_FLAG.value)
            replay = cid_for_structured(
                {
                    "checks": {"producer_flags_absent": False},
                    "issues": issues,
                    "verifier": PROOF_CARRYING_VERIFIER_INTERFACE,
                }
            )
            return ProofCarryingVerification(
                disposition=ProofCarryingDisposition.REJECTED,
                artifact_cid=str(artifact.get("artifact_cid") or ""),
                replay_receipt_cid=replay,
                issues=tuple(issues),
                checks={"producer_flags_absent": False},
            )
        except ProofCarryingArtifactError:
            issues.append(ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE.value)
            replay = cid_for_structured(
                {
                    "checks": {"mandatory_lineage_present": False},
                    "issues": issues,
                    "verifier": PROOF_CARRYING_VERIFIER_INTERFACE,
                }
            )
            return ProofCarryingVerification(
                disposition=ProofCarryingDisposition.REJECTED,
                artifact_cid=str(artifact.get("artifact_cid") or ""),
                replay_receipt_cid=replay,
                issues=tuple(issues),
                checks={"mandatory_lineage_present": False},
            )
    elif isinstance(artifact, ProofCarryingArtifact):
        bundle = artifact
    else:
        raise ProofCarryingArtifactError("artifact must be ProofCarryingArtifact or mapping")

    reconstructed = bundle.reconstructed_cid
    checks["content_identity_reconstructed"] = reconstructed == bundle.artifact_cid
    if reconstructed != bundle.artifact_cid:
        issues.append(ProofCarryingIssue.FORGED_CID.value)

    missing = bundle.lineage.missing_kinds()
    checks["mandatory_lineage_present"] = not missing
    if missing:
        issues.append(ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE.value)

    lineage_ok = True
    try:
        for kind, value in bundle.lineage.as_mapping().items():
            validate_cid(value)
        validate_cid(bundle.roots.tree_id)
        validate_cid(bundle.roots.semantic_state_root)
        validate_cid(bundle.roots.contract_root)
    except (ContentIdentityError, ProofCarryingArtifactError):
        lineage_ok = False
    checks["lineage_cids_well_formed"] = lineage_ok
    if not lineage_ok:
        issues.append(ProofCarryingIssue.MALFORMED_CID.value)

    expected_compact = _compact_checks_for(bundle.lineage, bundle.roots)
    compact_ok = all(
        bundle.compact_checks.get(name) == expected_compact[name]
        for name in _COMPACT_CHECK_NAMES
    )
    checks["compact_checks_reconstructed"] = compact_ok
    if not compact_ok:
        issues.append(ProofCarryingIssue.COMPACT_CHECK_MISMATCH.value)

    flags = _walk_producer_flags(bundle.to_dict())
    # Identity and verifier fields are allowed on the outer envelope.
    flags = tuple(
        item
        for item in flags
        if item.split(".")[-1] not in {"artifact_cid", "replay_receipt_cid"}
        and item
        not in {
            "semantic_authority",
            "grants_proof_authority",
            "grants_write_authority",
        }
    )
    checks["producer_flags_absent"] = not flags
    if flags:
        issues.append(ProofCarryingIssue.PRODUCER_FLAG.value)

    if expected_roots is not None:
        expected = (
            expected_roots
            if isinstance(expected_roots, ProofCarryingRoots)
            else ProofCarryingRoots.from_dict(expected_roots)
        )
        current = expected.to_dict() == bundle.roots.to_dict()
        checks["roots_current"] = current
        if not current:
            issues.append(ProofCarryingIssue.STALE_ROOT.value)
    else:
        checks["roots_current"] = True

    if expected_lineage is not None:
        expected_l = (
            expected_lineage
            if isinstance(expected_lineage, ArtifactLineage)
            else ArtifactLineage.from_dict(expected_lineage)
        )
        matched = expected_l.as_mapping() == bundle.lineage.as_mapping()
        checks["lineage_matches_expected"] = matched
        if not matched:
            issues.append(ProofCarryingIssue.LINEAGE_MISMATCH.value)

    unique_issues = tuple(dict.fromkeys(issues))
    replay_payload = {
        "artifact_cid": bundle.artifact_cid,
        "checks": checks,
        "issues": list(unique_issues),
        "reconstructed_cid": reconstructed,
        "verifier": PROOF_CARRYING_VERIFIER_INTERFACE,
    }
    return ProofCarryingVerification(
        disposition=(
            ProofCarryingDisposition.VALIDATED
            if not unique_issues
            else ProofCarryingDisposition.REJECTED
        ),
        artifact_cid=bundle.artifact_cid,
        replay_receipt_cid=cid_for_structured(replay_payload),
        issues=unique_issues,
        checks=checks,
    )


__all__ = (
    "CONTRACT_VERSION",
    "FORBIDDEN_PRODUCER_FLAGS",
    "MANDATORY_LINEAGE_KINDS",
    "PRODUCER_ID",
    "PROOF_CARRYING_ARTIFACT_INTERFACE",
    "PROOF_CARRYING_ARTIFACT_SCHEMA",
    "PROOF_CARRYING_VERIFICATION_SCHEMA",
    "PROOF_CARRYING_VERIFIER_INTERFACE",
    "ArtifactLineage",
    "ProofCarryingArtifact",
    "ProofCarryingArtifactAuthorityError",
    "ProofCarryingArtifactError",
    "ProofCarryingDisposition",
    "ProofCarryingIssue",
    "ProofCarryingRoots",
    "ProofCarryingVerification",
    "verify_proof_carrying_artifact",
)
