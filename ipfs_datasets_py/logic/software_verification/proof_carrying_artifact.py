"""Independent proof-carrying artifact bundle and verifier (LGCVF-090).

The bundle stores *references* to exact semantic, contract, abstract, proof,
test, static, security, policy, and authority lineage.  Optional extra refs may
bind source, delta, obligation, translation, model, toolchain, effect, or
invalidator handles.  The bundle does not carry proof bodies, source, or
producer pass-flags as correctness.

The verifier rebuilds content identities and compact checks from the payload
and rejects forged CIDs, stale roots, missing mandatory evidence, and producer
flags.  A stored CID or ``passed=true`` bit is never proof authority.

Lineage and root refs reuse the software-contract CID profile and also admit
ir-canonical-identity CIDv1 strings.  Reconstructed artifact, compact-check,
and replay identities use the existing ir-canonical-identity profile.  This
module does not create a generic receipt hierarchy or grant
semantic/proof/write authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.software_contracts.content import validate_cid


PROOF_CARRYING_ARTIFACT_INTERFACE: Final[str] = "ProofCarryingArtifact@1"
PROOF_CARRYING_ARTIFACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/software-verification/proof-carrying-artifact@1"
)
PROOF_CARRYING_ARTIFACT_IDENTITY_DOMAIN: Final[str] = (
    "logic.software-verification.proof-carrying-artifact"
)
PROOF_CARRYING_VERIFIER_INTERFACE: Final[str] = "ProofCarryingArtifactVerifier@1"
PROOF_CARRYING_VERIFICATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/software-verification/proof-carrying-verification@1"
)
PROOF_CARRYING_VERIFICATION_IDENTITY_DOMAIN: Final[str] = (
    "logic.software-verification.proof-carrying-verification"
)
PROOF_CARRYING_COMPACT_CHECK_DOMAIN: Final[str] = (
    "logic.software-verification.proof-carrying-compact-check"
)
PRODUCER_ID: Final[str] = "proof-carrying-artifact@1"
CONTRACT_VERSION: Final[int] = 1
_CID_ALPHABET: Final[frozenset[str]] = frozenset("abcdefghijklmnopqrstuvwxyz234567")

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

OPTIONAL_LINEAGE_KINDS: Final[tuple[str, ...]] = (
    "source",
    "delta",
    "obligation",
    "translation",
    "model",
    "toolchain",
    "effect",
    "invalidator",
    "residual",
)

FORBIDDEN_PRODUCER_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "accepted",
        "admitted",
        "approved",
        "complete",
        "completed",
        "completion_authority",
        "ok",
        "pass",
        "passed",
        "producer_pass",
        "producer_passed",
        "producer_verified",
        "production_authorized",
        "proved",
        "release_qualified",
        "self_certified",
        "success",
        "trusted",
        "valid",
        "verified",
    }
)

# Present on the reconstructed envelope as explicit *non*-authority bits.
_ENVELOPE_AUTHORITY_DENIALS: Final[frozenset[str]] = frozenset(
    {
        "semantic_authority",
        "grants_proof_authority",
        "grants_write_authority",
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


def _is_cidv1(value: str) -> bool:
    return (
        value.startswith("b")
        and len(value) >= 50
        and value == value.lower()
        and "\x00" not in value
        and set(value[1:]) <= _CID_ALPHABET
    )


def _identity(payload: Mapping[str, Any], *, domain: str, schema: str) -> str:
    return canonical_identity(dict(payload), domain=domain, schema_version=schema).cid


def _cid(value: object, label: str) -> str:
    """Admit software-contract and ir-canonical-identity CIDv1 strings."""

    text = _text(value, label)
    try:
        return validate_cid(text)
    except Exception as error:
        if _is_cidv1(text):
            return text
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


def _leaf_name(path: str) -> str:
    return path.split(".")[-1].split("[", 1)[0].strip().lower()


def _significant_producer_flags(payload: Any) -> tuple[str, ...]:
    return tuple(
        item
        for item in _walk_producer_flags(payload)
        if _leaf_name(item) not in _ENVELOPE_AUTHORITY_DENIALS
        and _leaf_name(item) not in {"artifact_cid", "replay_receipt_cid"}
    )


def _require_no_producer_flags(payload: Any, *, label: str) -> None:
    flags = _significant_producer_flags(payload)
    if flags:
        raise ProofCarryingArtifactAuthorityError(
            f"{label} contains producer flags: {flags[0]}"
        )


def _issue_from_construction(error: Exception) -> ProofCarryingIssue:
    message = str(error).lower()
    if isinstance(error, ProofCarryingArtifactAuthorityError) or "producer flag" in message:
        return ProofCarryingIssue.PRODUCER_FLAG
    if "not a software-contract cid" in message:
        return ProofCarryingIssue.MALFORMED_CID
    if "identity mismatch" in message or "forged" in message:
        return ProofCarryingIssue.FORGED_CID
    if "compact check" in message:
        return ProofCarryingIssue.COMPACT_CHECK_MISMATCH
    return ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE


def _claimed_cid(payload: Mapping[str, Any]) -> str:
    claimed = payload.get("artifact_cid")
    if isinstance(claimed, str) and claimed:
        try:
            return _cid(claimed, "artifact_cid")
        except ProofCarryingArtifactError:
            return ""
    return ""


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
        _require_no_producer_flags(extras, label="extra_refs")
        normalized: dict[str, str] = {}
        for key, value in extras.items():
            kind = _text(key, "extra_refs key")
            if kind in MANDATORY_LINEAGE_KINDS:
                raise ProofCarryingArtifactError(
                    "extra_refs cannot override mandatory lineage kinds"
                )
            normalized[kind] = _cid(value, f"extra_refs.{kind}")
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
        refs: dict[str, str] = {}
        missing: list[str] = []
        for kind in MANDATORY_LINEAGE_KINDS:
            field_name = f"{kind}_ref"
            if field_name not in payload or payload.get(field_name) in (None, ""):
                missing.append(kind)
            else:
                refs[field_name] = str(payload.get(field_name) or "")
        if missing:
            raise ProofCarryingArtifactError(
                "mandatory lineage missing: " + ", ".join(missing)
            )
        return cls(
            semantic_ref=refs["semantic_ref"],
            contract_ref=refs["contract_ref"],
            abstract_ref=refs["abstract_ref"],
            proof_ref=refs["proof_ref"],
            test_ref=refs["test_ref"],
            static_ref=refs["static_ref"],
            security_ref=refs["security_ref"],
            policy_ref=refs["policy_ref"],
            authority_ref=refs["authority_ref"],
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
        missing = [
            name
            for name in ("repository_id", "tree_id", "semantic_state_root", "contract_root")
            if name not in payload or payload.get(name) in (None, "")
        ]
        if missing:
            raise ProofCarryingArtifactError(
                "mandatory roots missing: " + ", ".join(missing)
            )
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            tree_id=str(payload.get("tree_id") or ""),
            semantic_state_root=str(payload.get("semantic_state_root") or ""),
            contract_root=str(payload.get("contract_root") or ""),
        )


def rebuild_compact_checks(lineage: ArtifactLineage, roots: ProofCarryingRoots) -> dict[str, str]:
    """Independently reconstruct compact check identities from lineage and roots."""

    return {
        "lineage": _identity(
            lineage.as_mapping(),
            domain=PROOF_CARRYING_COMPACT_CHECK_DOMAIN,
            schema="lineage",
        ),
        "roots": _identity(
            roots.to_dict(),
            domain=PROOF_CARRYING_COMPACT_CHECK_DOMAIN,
            schema="roots",
        ),
    }


def _compact_checks_for(lineage: ArtifactLineage, roots: ProofCarryingRoots) -> dict[str, str]:
    return rebuild_compact_checks(lineage, roots)


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
        _require_no_producer_flags(checks, label="compact_checks")
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
        claimed = self.artifact_cid
        if claimed:
            claimed = _cid(claimed, "artifact_cid")
        # Store the claim when present so the verifier can independently
        # reconstruct and reject a forged identity. Construction never treats
        # a matching CID as proof authority.
        object.__setattr__(
            self,
            "artifact_cid",
            claimed
            or _identity(
                preimage,
                domain=PROOF_CARRYING_ARTIFACT_IDENTITY_DOMAIN,
                schema=PROOF_CARRYING_ARTIFACT_SCHEMA,
            ),
        )

    @property
    def reconstructed_cid(self) -> str:
        return _identity(
            _artifact_preimage(
                lineage=self.lineage,
                roots=self.roots,
                compact_checks=self.compact_checks,
                producer_id=self.producer_id,
                metadata=self.metadata,
            ),
            domain=PROOF_CARRYING_ARTIFACT_IDENTITY_DOMAIN,
            schema=PROOF_CARRYING_ARTIFACT_SCHEMA,
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
        _require_no_producer_flags(payload, label="artifact")
        lineage_payload = payload.get("lineage")
        roots_payload = payload.get("roots")
        if lineage_payload in (None, {}):
            raise ProofCarryingArtifactError("mandatory lineage missing")
        if roots_payload in (None, {}):
            raise ProofCarryingArtifactError("mandatory roots missing")
        return cls(
            lineage=ArtifactLineage.from_dict(_mapping(lineage_payload, "lineage")),
            roots=ProofCarryingRoots.from_dict(_mapping(roots_payload, "roots")),
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
    checks: Mapping[str, Any] = field(default_factory=dict)
    interface: str = PROOF_CARRYING_VERIFIER_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ProofCarryingDisposition):
            object.__setattr__(
                self,
                "disposition",
                ProofCarryingDisposition(self.disposition),
            )
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
        if self.disposition is ProofCarryingDisposition.VALIDATED and self.issues:
            raise ProofCarryingArtifactError("validated disposition cannot carry issues")
        if any(key in FORBIDDEN_PRODUCER_FLAGS for key in self.checks):
            raise ProofCarryingArtifactError(
                "verification result must not store producer flags as checks"
            )

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


def _reject(
    *,
    artifact_cid: str,
    issues: Sequence[str],
    checks: Mapping[str, Any],
) -> ProofCarryingVerification:
    unique_issues = tuple(dict.fromkeys(issues))
    replay = _identity(
        {
            "artifact_cid": artifact_cid,
            "checks": dict(checks),
            "disposition": ProofCarryingDisposition.REJECTED.value,
            "issues": list(unique_issues),
            "verifier": PROOF_CARRYING_VERIFIER_INTERFACE,
        },
        domain=PROOF_CARRYING_VERIFICATION_IDENTITY_DOMAIN,
        schema=PROOF_CARRYING_VERIFICATION_SCHEMA,
    )
    return ProofCarryingVerification(
        disposition=ProofCarryingDisposition.REJECTED,
        artifact_cid=artifact_cid,
        replay_receipt_cid=replay,
        issues=unique_issues,
        checks=dict(checks),
    )


def verify_proof_carrying_artifact(
    artifact: ProofCarryingArtifact | Mapping[str, Any],
    *,
    expected_roots: ProofCarryingRoots | Mapping[str, Any] | None = None,
    expected_lineage: ArtifactLineage | Mapping[str, Any] | None = None,
) -> ProofCarryingVerification:
    """Rebuild identities and compact checks; reject forged/stale/omitted evidence."""

    checks: dict[str, Any] = {}

    if isinstance(artifact, Mapping):
        flags = _significant_producer_flags(artifact)
        if flags:
            checks["producer_flags_absent"] = False
            checks["producer_flag_paths"] = list(flags)
            return _reject(
                artifact_cid=_claimed_cid(artifact),
                issues=(ProofCarryingIssue.PRODUCER_FLAG.value,),
                checks=checks,
            )
        try:
            bundle = ProofCarryingArtifact.from_dict(artifact)
        except ProofCarryingArtifactError as error:
            issue = _issue_from_construction(error)
            checks["construction_error"] = str(error)
            if issue is ProofCarryingIssue.PRODUCER_FLAG:
                checks["producer_flags_absent"] = False
            if issue is ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE:
                checks["mandatory_lineage_present"] = False
            return _reject(
                artifact_cid=_claimed_cid(artifact),
                issues=(issue.value,),
                checks=checks,
            )
    elif isinstance(artifact, ProofCarryingArtifact):
        bundle = artifact
    else:
        raise ProofCarryingArtifactError("artifact must be ProofCarryingArtifact or mapping")

    reconstructed = bundle.reconstructed_cid
    checks["content_identity_reconstructed"] = reconstructed == bundle.artifact_cid
    issues: list[str] = []
    if reconstructed != bundle.artifact_cid:
        issues.append(ProofCarryingIssue.FORGED_CID.value)

    missing = bundle.lineage.missing_kinds()
    checks["mandatory_lineage_present"] = not missing
    if missing:
        checks["missing_lineage_kinds"] = list(missing)
        issues.append(ProofCarryingIssue.MISSING_MANDATORY_EVIDENCE.value)

    lineage_ok = True
    try:
        for value in bundle.lineage.as_mapping().values():
            _cid(value, "lineage_ref")
        _cid(bundle.roots.tree_id, "tree_id")
        _cid(bundle.roots.semantic_state_root, "semantic_state_root")
        _cid(bundle.roots.contract_root, "contract_root")
        for name, value in bundle.compact_checks.items():
            _cid(value, f"compact_checks.{name}")
        _cid(bundle.artifact_cid, "artifact_cid")
    except ProofCarryingArtifactError:
        lineage_ok = False
    checks["lineage_cids_well_formed"] = lineage_ok
    if not lineage_ok:
        issues.append(ProofCarryingIssue.MALFORMED_CID.value)

    expected_compact = _compact_checks_for(bundle.lineage, bundle.roots)
    compact_ok = all(
        bundle.compact_checks.get(name) == expected_compact[name]
        for name in _COMPACT_CHECK_NAMES
    ) and all(name in bundle.compact_checks for name in _COMPACT_CHECK_NAMES)
    checks["compact_checks_reconstructed"] = compact_ok
    if not compact_ok:
        issues.append(ProofCarryingIssue.COMPACT_CHECK_MISMATCH.value)

    flags = _significant_producer_flags(bundle.to_dict())
    checks["producer_flags_absent"] = not flags
    if flags:
        checks["producer_flag_paths"] = list(flags)
        issues.append(ProofCarryingIssue.PRODUCER_FLAG.value)

    if expected_roots is not None:
        try:
            expected = (
                expected_roots
                if isinstance(expected_roots, ProofCarryingRoots)
                else ProofCarryingRoots.from_dict(expected_roots)
            )
        except ProofCarryingArtifactError:
            checks["roots_current"] = False
            issues.append(ProofCarryingIssue.STALE_ROOT.value)
        else:
            current = expected.to_dict() == bundle.roots.to_dict()
            checks["roots_current"] = current
            if not current:
                issues.append(ProofCarryingIssue.STALE_ROOT.value)
    else:
        checks["roots_current"] = True

    if expected_lineage is not None:
        try:
            expected_l = (
                expected_lineage
                if isinstance(expected_lineage, ArtifactLineage)
                else ArtifactLineage.from_dict(expected_lineage)
            )
        except ProofCarryingArtifactError:
            checks["lineage_matches_expected"] = False
            issues.append(ProofCarryingIssue.LINEAGE_MISMATCH.value)
        else:
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
        replay_receipt_cid=_identity(
            replay_payload,
            domain=PROOF_CARRYING_VERIFICATION_IDENTITY_DOMAIN,
            schema=PROOF_CARRYING_VERIFICATION_SCHEMA,
        ),
        issues=unique_issues,
        checks=checks,
    )


def require_verified_artifact(
    artifact: ProofCarryingArtifact | Mapping[str, Any],
    *,
    expected_roots: ProofCarryingRoots | Mapping[str, Any] | None = None,
    expected_lineage: ArtifactLineage | Mapping[str, Any] | None = None,
) -> ProofCarryingVerification:
    """Fail closed when independent verification does not validate the artifact."""

    result = verify_proof_carrying_artifact(
        artifact,
        expected_roots=expected_roots,
        expected_lineage=expected_lineage,
    )
    if not result.valid:
        raise ProofCarryingArtifactError(
            "proof-carrying artifact failed independent verification: "
            + ", ".join(result.issues)
        )
    return result


__all__ = (
    "CONTRACT_VERSION",
    "FORBIDDEN_PRODUCER_FLAGS",
    "MANDATORY_LINEAGE_KINDS",
    "OPTIONAL_LINEAGE_KINDS",
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
    "rebuild_compact_checks",
    "require_verified_artifact",
    "verify_proof_carrying_artifact",
)
