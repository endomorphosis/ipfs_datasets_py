"""Artifact-preserving State Laws publication-package planning.

This module is the deliberately narrow bridge between the completed local
State Laws release and the shared append-only Hugging Face publisher.  It does
not build, normalize, shard, embed, cluster, or re-encode corpus artifacts.

The bridge performs three local-only operations:

* re-read the canonical exact-51 ``manifest.json`` and re-hash every artifact
  descriptor against the existing release tree;
* add one publication descriptor for the *existing* ``manifest.json`` bytes
  (the local manifest cannot self-describe without a hash cycle); and
* ask :class:`~ipfs_datasets_py.huggingface.publisher.HuggingFaceReleasePublisher`
  for its deterministic dry-run plan.

No live publication function is exposed. A caller crossing the remote mutation
boundary must seal :func:`require_state_laws_policy_binding` to one exact plan.
The generic publisher then reopens the local package and authorization fixture,
checks loaded/current verifier identity, and re-evaluates that proof before any
Hub API call.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.huggingface.publication_profile import (
    BASE_PROHIBITED_OPERATIONS,
    HuggingFacePublicationProfile,
)
from ipfs_datasets_py.huggingface.publisher import (
    HuggingFaceReleasePublisher,
    PublicationPlan,
)
from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    require_live_source_rights_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    MANIFEST_PATH,
    verify_state_laws_local_release_manifest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_CREDENTIALS_SCOPE,
    PREVIOUS_PUBLIC_PIN,
    REQUIRED_LIVE_MUTATION_GATES,
    LiveMutationRequest,
    PublicationAuthorization,
    assert_rollback_pin_preserved,
    assert_target_authorized,
    validate_exact_51_coverage,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    GOAL_ID as STATE_LAWS_POLICY_GOAL_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    SCHEMA_VERSION as STATE_LAWS_POLICY_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    SOURCE_RIGHTS_RECEIPT_RELPATH,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SCHEMA_VERSION as RELEASE_SCHEMA_VERSION,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    confine_path,
    file_digest,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import canonical_json_bytes

SCHEMA_VERSION: Final = "state-laws-artifact-preserving-publication-package/v1"
DRY_RUN_SCHEMA_VERSION: Final = "state-laws-publication-dry-run/v1"
LIVE_POLICY_PROOF_SCHEMA_VERSION: Final = (
    "state-laws-live-publication-policy-proof/v2"
)

STATE_LAWS_PROFILE_ID: Final = "state-laws"
STATE_LAWS_PROGRAM_ID: Final = "state-laws-sparse-graphrag"
STATE_LAWS_PLAN_SCHEMA: Final = "state-laws-hf-publication-plan/v1"
STATE_LAWS_RECEIPT_SCHEMA: Final = "state-laws-hf-publication-receipt/v1"
STATE_LAWS_RELEASE_PREFIX_TEMPLATE: Final = "data/state_laws/{release_id}"
STATE_LAWS_POINTER_PATH: Final = "runtime/state_laws_release_pointer.json"
STATE_LAWS_COMMIT_MESSAGE: Final = (
    "state-laws: append-only immutable exact-51 public release"
)

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False
REENCODES_PHYSICAL_ARTIFACTS: Final = False

class StateLawsPublicationPackageError(ValueError):
    """Raised when a local release cannot be planned without weakening it."""


def _canonical_mapping(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StateLawsPublicationPackageError(f"{label} must be a mapping")
    try:
        normalized = json.loads(canonical_json_bytes(dict(value)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            f"{label} must be canonical JSON data"
        ) from exc
    if type(normalized) is not dict:
        raise StateLawsPublicationPackageError(f"{label} must be a JSON object")
    return normalized


def _require_sha256(value: Any, *, label: str) -> str:
    text = str(value or "")
    if (
        len(text) != 64
        or text != text.casefold()
        or any(character not in "0123456789abcdef" for character in text)
    ):
        raise StateLawsPublicationPackageError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return text


def _read_regular_file_nofollow(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    try:
        from ipfs_datasets_py.huggingface.publisher import (
            _read_regular_file_nofollow_components,
        )

        return _read_regular_file_nofollow_components(
            path,
            label=label,
            maximum_bytes=maximum_bytes,
        )
    except Exception as exc:
        if isinstance(exc, StateLawsPublicationPackageError):
            raise
        raise StateLawsPublicationPackageError(
            f"cannot reopen {label} without following symlinks: {exc}"
        ) from exc


def _reject_duplicate_json_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StateLawsPublicationPackageError(
                f"authorization fixture contains duplicate JSON key: {key!r}"
            )
        result[key] = value
    return result


def _policy_verifier_source_identity() -> dict[str, Any]:
    """Use the shared source gate for loaded/current verifier identity."""

    from ipfs_datasets_py.processors.legal_data import (
        state_laws_publication_policy as policy_module,
    )
    from ipfs_datasets_py.huggingface.publisher import (
        _StateLawsLivePolicyBoundary,
    )

    try:
        return _StateLawsLivePolicyBoundary.attest_target(
            policy_module,
            label="state_laws_publication_policy_verifier",
            source_relative_path=(
                "ipfs_datasets_py/processors/legal_data/"
                "state_laws_publication_policy.py"
            ),
        )
    except Exception as exc:
        if isinstance(exc, StateLawsPublicationPackageError):
            raise
        raise StateLawsPublicationPackageError(
            f"State Laws policy verifier source attestation failed: {exc}"
        ) from exc


def _fresh_policy_authorization() -> tuple[PublicationAuthorization, str, int]:
    """Reopen and parse the fixed authorization fixture without its cache."""

    from ipfs_datasets_py.processors.legal_data import (
        state_laws_publication_policy as policy_module,
    )

    fixture_path = policy_module.default_authorization_fixture_path()
    encoded = _read_regular_file_nofollow(
        fixture_path,
        label="State Laws publication authorization fixture",
        maximum_bytes=2 * 1024 * 1024,
    )
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            "State Laws publication authorization fixture is malformed"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StateLawsPublicationPackageError(
            "State Laws publication authorization fixture root must be an object"
        )
    expected_payload = policy_module.sealed_authorization_fixture_payload()
    if dict(payload) != expected_payload:
        raise StateLawsPublicationPackageError(
            "State Laws publication authorization fixture differs from the "
            "allowlisted policy fixture"
        )
    try:
        authorization = PublicationAuthorization.from_mapping(payload)
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            f"State Laws publication authorization fixture is invalid: {exc}"
        ) from exc
    return authorization, sha256(encoded).hexdigest(), len(encoded)


def state_laws_publication_profile() -> HuggingFacePublicationProfile:
    """Return the State Laws identity/layout for the shared publisher."""

    return HuggingFacePublicationProfile(
        profile_id=STATE_LAWS_PROFILE_ID,
        program_id=STATE_LAWS_PROGRAM_ID,
        goal_id=STATE_LAWS_POLICY_GOAL_ID,
        plan_schema_version=STATE_LAWS_PLAN_SCHEMA,
        receipt_schema_version=STATE_LAWS_RECEIPT_SCHEMA,
        canonical_release_schema=RELEASE_SCHEMA_VERSION,
        repository_id=DEFAULT_DATASET_REPO_ID,
        repository_type="dataset",
        release_prefix_template=STATE_LAWS_RELEASE_PREFIX_TEMPLATE,
        pointer_path=STATE_LAWS_POINTER_PATH,
        target_revision="main",
        commit_message=STATE_LAWS_COMMIT_MESSAGE,
        prohibited_operations=BASE_PROHIBITED_OPERATIONS,
        require_pinned_verification_before_promotion=True,
        allow_remote_write_on_dry_run=False,
        metadata={
            "artifact_preserving": True,
            "policy_schema_version": STATE_LAWS_POLICY_SCHEMA_VERSION,
            "program": STATE_LAWS_PROGRAM_ID,
        },
    )


@dataclass(frozen=True, slots=True)
class StateLawsPublicationPackage:
    """Verified local descriptors plus the existing manifest byte descriptor."""

    output_root: str
    manifest_relative_path: str
    manifest_digest: str
    manifest_file_sha256: str
    manifest_size_bytes: int
    release_id: str
    artifact_descriptors: tuple[Mapping[str, Any], ...]
    manifest_descriptor: Mapping[str, Any]
    policy_binding: Mapping[str, Any]

    @property
    def manifest_path(self) -> Path:
        return Path(self.output_root) / self.manifest_relative_path

    def to_publisher_manifest(self) -> dict[str, Any]:
        """Return the descriptor protocol consumed by the shared publisher."""

        verify_state_laws_publication_package_identity(self)
        descriptors = [dict(item) for item in self.artifact_descriptors]
        descriptors.append(dict(self.manifest_descriptor))
        descriptors.sort(key=lambda item: str(item["relative_path"]))
        return {
            "artifact_preserving": True,
            "descriptors": descriptors,
            "manifest_file_sha256": self.manifest_file_sha256,
            "release_id": self.release_id,
            "release_sha256": self.manifest_digest,
            "schema_version": SCHEMA_VERSION,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_descriptor_count": len(self.artifact_descriptors),
            "artifact_preserving": True,
            "authorizes_hub_upload": False,
            "authorizes_publication": False,
            "manifest_descriptor": dict(self.manifest_descriptor),
            "manifest_digest": self.manifest_digest,
            "manifest_file_sha256": self.manifest_file_sha256,
            "manifest_relative_path": self.manifest_relative_path,
            "manifest_size_bytes": self.manifest_size_bytes,
            "network_io_performed": False,
            "physical_artifacts_reencoded": False,
            "policy_binding": dict(self.policy_binding),
            "release_id": self.release_id,
            "schema_version": SCHEMA_VERSION,
        }


def verify_state_laws_publication_package_identity(
    package: StateLawsPublicationPackage,
) -> StateLawsPublicationPackage:
    """Rebind a package and release ID to its current canonical manifest bytes.

    This is the final local identity gate used immediately before publication
    planning or live-policy evaluation.  It prevents a forged package object,
    a syntactically valid wrong release ID, or a post-verification manifest
    path swap from selecting a different immutable release prefix.
    """

    if not isinstance(package, StateLawsPublicationPackage):
        raise StateLawsPublicationPackageError(
            "package must be a verified StateLawsPublicationPackage"
        )
    manifest_digest = package.manifest_digest
    if (
        not isinstance(manifest_digest, str)
        or len(manifest_digest) != 64
        or any(character not in "0123456789abcdef" for character in manifest_digest)
    ):
        raise StateLawsPublicationPackageError(
            "publication package manifest_digest must be lowercase SHA-256"
        )
    expected_release_id = f"sha256-{manifest_digest}"
    if package.release_id != expected_release_id:
        raise StateLawsPublicationPackageError(
            "publication package release_id does not match its manifest digest"
        )
    if package.manifest_relative_path != MANIFEST_PATH:
        raise StateLawsPublicationPackageError(
            "publication package manifest path is not canonical"
        )

    try:
        root = Path(package.output_root).expanduser().resolve(strict=True)
        manifest_path = confine_path(root, package.manifest_relative_path)
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise StateLawsPublicationPackageError(
                "publication package manifest is missing or unsafe"
            )
        encoded = manifest_path.read_bytes()
        payload = json.loads(encoded.decode("utf-8"))
    except StateLawsPublicationPackageError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            "publication package manifest could not be reverified"
        ) from exc
    if type(payload) is not dict:
        raise StateLawsPublicationPackageError(
            "publication package manifest root must be an object"
        )
    canonical = canonical_json_bytes(payload)
    if encoded not in {canonical, canonical + b"\n"}:
        raise StateLawsPublicationPackageError(
            "publication package manifest bytes are not canonical"
        )
    observed_manifest_digest = digest_mapping(payload)
    if observed_manifest_digest != manifest_digest:
        raise StateLawsPublicationPackageError(
            "publication package manifest content identity does not match "
            "manifest_digest"
        )
    observed_file_sha256 = sha256(encoded).hexdigest()
    if (
        len(encoded) != package.manifest_size_bytes
        or observed_file_sha256 != package.manifest_file_sha256
    ):
        raise StateLawsPublicationPackageError(
            "publication package manifest byte descriptor drifted"
        )

    descriptor = package.manifest_descriptor
    if (
        not isinstance(descriptor, Mapping)
        or descriptor.get("relative_path") != MANIFEST_PATH
        or descriptor.get("sha256") != observed_file_sha256
        or descriptor.get("size_bytes") != len(encoded)
    ):
        raise StateLawsPublicationPackageError(
            "publication package manifest descriptor is not identity-bound"
        )
    binding = package.policy_binding
    if (
        not isinstance(binding, Mapping)
        or binding.get("final_manifest_digest") != manifest_digest
        or binding.get("dataset_repo_id") != DEFAULT_DATASET_REPO_ID
    ):
        raise StateLawsPublicationPackageError(
            "publication package policy binding is not identity-bound"
        )
    return package


def prepare_state_laws_publication_package(
    output_root: str | Path,
) -> StateLawsPublicationPackage:
    """Reverify one completed local release without modifying any file."""

    try:
        release = verify_state_laws_local_release_manifest(output_root)
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            f"completed State Laws local release failed verification: {exc}"
        ) from exc
    root = Path(release.output_root)
    manifest_path = release.path
    payload = dict(release.payload)

    # Replay the fixed-path live rights authority at the final local bridge as
    # well as inside the release verifier.  Publication packaging must not be
    # able to rely on an old manifest summary after policy/catalog drift.
    try:
        rights_path = confine_path(root, SOURCE_RIGHTS_RECEIPT_RELPATH)
        if rights_path.is_symlink():
            raise StateLawsPublicationPackageError(
                "source-rights compliance receipt is an unsafe symlink"
            )
        rights_payload = json.loads(rights_path.read_bytes())
        if type(rights_payload) is not dict:
            raise StateLawsPublicationPackageError(
                "source-rights compliance receipt root must be an object"
            )
        require_live_source_rights_receipt(rights_payload)
    except StateLawsPublicationPackageError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            f"source-rights compliance receipt failed final live verification: {exc}"
        ) from exc

    # Bind the package identity to the same sealed target/rollback policy used
    # at the future mutation boundary.  These checks grant no authorization.
    try:
        validate_exact_51_coverage(payload["jurisdictions"])
        assert_target_authorized(payload["dataset_repo_id"])
        assert_rollback_pin_preserved(PREVIOUS_PUBLIC_PIN)
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            "completed local manifest failed its State Laws policy binding"
        ) from exc

    manifest_size, manifest_file_digest = file_digest(manifest_path)
    manifest_digest = release.manifest_digest
    release_id = f"sha256-{manifest_digest}"
    manifest_descriptor = MappingProxyType(
        {
            "family": "manifest",
            "media_type": "application/json",
            "relative_path": MANIFEST_PATH,
            "row_count": 0,
            "schema_id": RELEASE_SCHEMA_VERSION,
            "sha256": manifest_file_digest.hex(),
            "size_bytes": manifest_size,
        }
    )
    policy_binding = MappingProxyType(
        {
            "credentials_scope": DEFAULT_CREDENTIALS_SCOPE,
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "final_manifest_digest": manifest_digest,
            "jurisdictions": list(CANONICAL_JURISDICTION_ORDER),
            "live_mutation_authorized": False,
            "live_mutation_evaluated": False,
            "policy_schema_version": STATE_LAWS_POLICY_SCHEMA_VERSION,
            "previous_public_pin": PREVIOUS_PUBLIC_PIN,
            "remote_mutation_attempted": False,
            "required_live_mutation_gates": list(REQUIRED_LIVE_MUTATION_GATES),
        }
    )
    package = StateLawsPublicationPackage(
        output_root=str(root),
        manifest_relative_path=MANIFEST_PATH,
        manifest_digest=manifest_digest,
        manifest_file_sha256=manifest_file_digest.hex(),
        manifest_size_bytes=manifest_size,
        release_id=release_id,
        artifact_descriptors=tuple(
            MappingProxyType(dict(descriptor))
            for descriptor in payload["artifacts"]
        ),
        manifest_descriptor=manifest_descriptor,
        policy_binding=policy_binding,
    )
    return verify_state_laws_publication_package_identity(package)


@dataclass(frozen=True, slots=True)
class StateLawsPublicationDryRun:
    """Shared-publisher plan and receipt; always local and non-mutating."""

    package: StateLawsPublicationPackage
    profile: HuggingFacePublicationProfile
    plan: PublicationPlan
    receipt: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_hub_upload": False,
            "authorizes_publication": False,
            "network_io_performed": False,
            "package": self.package.to_dict(),
            "physical_artifacts_reencoded": False,
            "plan": self.plan.to_dict(),
            "profile": self.profile.to_dict(),
            "receipt": dict(self.receipt),
            "remote_mutation_attempted": False,
            "schema_version": DRY_RUN_SCHEMA_VERSION,
        }


@dataclass(frozen=True, slots=True)
class StateLawsLivePolicyProof:
    """Content-addressed proof re-evaluated at the generic live boundary."""

    schema_version: str
    profile_id: str
    program_id: str
    profile_digest: str
    plan_digest: str
    release_id: str
    manifest_digest: str
    release_digest: str
    repository_id: str
    repository_type: str
    target_revision: str
    operation: str
    phase: str
    request: Mapping[str, Any]
    request_digest: str
    decision: Mapping[str, Any]
    decision_digest: str
    authorization_fixture_sha256: str
    authorization_fixture_size_bytes: int
    policy_verifier_identity: Mapping[str, Any]
    policy_verifier_identity_digest: str
    final_boundary_identity: Mapping[str, Any]
    final_boundary_identity_digest: str
    proof_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != LIVE_POLICY_PROOF_SCHEMA_VERSION:
            raise StateLawsPublicationPackageError(
                "unsupported State Laws live-policy proof schema"
            )
        for field_name in (
            "profile_digest",
            "plan_digest",
            "manifest_digest",
            "release_digest",
            "request_digest",
            "decision_digest",
            "authorization_fixture_sha256",
            "policy_verifier_identity_digest",
            "final_boundary_identity_digest",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), label=field_name),
            )
        for field_name in (
            "profile_id",
            "program_id",
            "release_id",
            "repository_id",
            "repository_type",
            "target_revision",
            "operation",
            "phase",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value.strip() != value:
                raise StateLawsPublicationPackageError(
                    f"{field_name} must be non-empty canonical text"
                )
        if (
            not isinstance(self.authorization_fixture_size_bytes, int)
            or isinstance(self.authorization_fixture_size_bytes, bool)
            or self.authorization_fixture_size_bytes <= 0
        ):
            raise StateLawsPublicationPackageError(
                "authorization_fixture_size_bytes must be positive"
            )

        request = _canonical_mapping(self.request, label="policy proof request")
        decision = _canonical_mapping(self.decision, label="policy proof decision")
        policy_identity = _canonical_mapping(
            self.policy_verifier_identity,
            label="policy verifier identity",
        )
        boundary_identity = _canonical_mapping(
            self.final_boundary_identity,
            label="final publication boundary identity",
        )
        if sha256(canonical_json_bytes(request)).hexdigest() != self.request_digest:
            raise StateLawsPublicationPackageError(
                "State Laws policy proof request digest mismatch"
            )
        if sha256(canonical_json_bytes(decision)).hexdigest() != self.decision_digest:
            raise StateLawsPublicationPackageError(
                "State Laws policy proof decision digest mismatch"
            )
        if (
            sha256(canonical_json_bytes(policy_identity)).hexdigest()
            != self.policy_verifier_identity_digest
        ):
            raise StateLawsPublicationPackageError(
                "State Laws policy verifier identity digest mismatch"
            )
        if (
            sha256(canonical_json_bytes(boundary_identity)).hexdigest()
            != self.final_boundary_identity_digest
        ):
            raise StateLawsPublicationPackageError(
                "State Laws final publication boundary identity digest mismatch"
            )
        object.__setattr__(self, "request", MappingProxyType(request))
        object.__setattr__(self, "decision", MappingProxyType(decision))
        object.__setattr__(
            self,
            "policy_verifier_identity",
            MappingProxyType(policy_identity),
        )
        object.__setattr__(
            self,
            "final_boundary_identity",
            MappingProxyType(boundary_identity),
        )
        expected = sha256(canonical_json_bytes(self._identity_payload())).hexdigest()
        if self.proof_digest and self.proof_digest != expected:
            raise StateLawsPublicationPackageError(
                "State Laws live-policy proof digest mismatch"
            )
        object.__setattr__(self, "proof_digest", expected)

    @property
    def authorized(self) -> bool:
        return self.decision.get("authorized") is True

    @property
    def final_manifest_digest(self) -> str:
        return self.manifest_digest

    @property
    def dataset_repo_id(self) -> str:
        return self.repository_id

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "authorization_fixture_sha256": self.authorization_fixture_sha256,
            "authorization_fixture_size_bytes": (
                self.authorization_fixture_size_bytes
            ),
            "decision": dict(self.decision),
            "decision_digest": self.decision_digest,
            "final_boundary_identity": dict(self.final_boundary_identity),
            "final_boundary_identity_digest": (
                self.final_boundary_identity_digest
            ),
            "manifest_digest": self.manifest_digest,
            "operation": self.operation,
            "phase": self.phase,
            "plan_digest": self.plan_digest,
            "policy_verifier_identity": dict(self.policy_verifier_identity),
            "policy_verifier_identity_digest": (
                self.policy_verifier_identity_digest
            ),
            "profile_digest": self.profile_digest,
            "profile_id": self.profile_id,
            "program_id": self.program_id,
            "release_digest": self.release_digest,
            "release_id": self.release_id,
            "repository_id": self.repository_id,
            "repository_type": self.repository_type,
            "request": dict(self.request),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "target_revision": self.target_revision,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity_payload(), "proof_digest": self.proof_digest}

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "StateLawsLivePolicyProof":
        if not isinstance(value, Mapping):
            raise StateLawsPublicationPackageError(
                "State Laws live-policy proof must be a mapping"
            )
        try:
            return cls(
                schema_version=value["schema_version"],
                profile_id=value["profile_id"],
                program_id=value["program_id"],
                profile_digest=value["profile_digest"],
                plan_digest=value["plan_digest"],
                release_id=value["release_id"],
                manifest_digest=value["manifest_digest"],
                release_digest=value["release_digest"],
                repository_id=value["repository_id"],
                repository_type=value["repository_type"],
                target_revision=value["target_revision"],
                operation=value["operation"],
                phase=value["phase"],
                request=value["request"],
                request_digest=value["request_digest"],
                decision=value["decision"],
                decision_digest=value["decision_digest"],
                authorization_fixture_sha256=(
                    value["authorization_fixture_sha256"]
                ),
                authorization_fixture_size_bytes=(
                    value["authorization_fixture_size_bytes"]
                ),
                policy_verifier_identity=value["policy_verifier_identity"],
                policy_verifier_identity_digest=(
                    value["policy_verifier_identity_digest"]
                ),
                final_boundary_identity=value["final_boundary_identity"],
                final_boundary_identity_digest=(
                    value["final_boundary_identity_digest"]
                ),
                proof_digest=value.get("proof_digest", ""),
            )
        except KeyError as exc:
            raise StateLawsPublicationPackageError(
                f"State Laws live-policy proof is missing {exc.args[0]}"
            ) from exc


def plan_state_laws_publication_dry_run(
    output_root: str | Path,
    *,
    api: Any | None = None,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
    audited_parent_commit: str = "",
) -> StateLawsPublicationDryRun:
    """Return a deterministic shared-publisher plan with zero network calls."""

    package = prepare_state_laws_publication_package(output_root)
    profile = state_laws_publication_profile()
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        package.to_publisher_manifest(),
        local_root=package.output_root,
        existing_remote_paths=existing_remote_paths,
        existing_remote_digests=existing_remote_digests,
        audited_parent_commit=audited_parent_commit,
    )
    if (
        plan.release_id != package.release_id
        or plan.release_sha256 != package.manifest_digest
        or plan.repository_id != DEFAULT_DATASET_REPO_ID
    ):
        raise StateLawsPublicationPackageError(
            "shared publisher plan drifted from the verified State Laws package"
        )
    receipt = publisher.build_publication_receipt(
        plan=plan,
        status="dry_run_only",
    )
    if receipt.get("remote_write_performed") is not False:
        raise StateLawsPublicationPackageError(
            "dry-run receipt unexpectedly records a remote write"
        )
    return StateLawsPublicationDryRun(
        package=package,
        profile=profile,
        plan=plan,
        receipt=MappingProxyType(dict(receipt)),
    )


def _verify_state_laws_plan_binding(
    package: StateLawsPublicationPackage,
    plan: PublicationPlan,
    profile: HuggingFacePublicationProfile,
) -> None:
    if not isinstance(plan, PublicationPlan):
        raise StateLawsPublicationPackageError(
            "State Laws live-policy proof requires a PublicationPlan"
        )
    official = state_laws_publication_profile()
    if canonical_json_bytes(profile.to_dict()) != canonical_json_bytes(
        official.to_dict()
    ):
        raise StateLawsPublicationPackageError(
            "State Laws live publication profile is not the official profile"
        )
    if (
        plan.schema_version != STATE_LAWS_PLAN_SCHEMA
        or plan.metadata.get("profile_id") != STATE_LAWS_PROFILE_ID
        or plan.metadata.get("program_id") != STATE_LAWS_PROGRAM_ID
        or plan.metadata.get("goal_id") != STATE_LAWS_POLICY_GOAL_ID
        or plan.repository_id != official.repository_id
        or plan.repository_type != official.repository_type
        or plan.target_revision != official.target_revision
        or plan.release_id != package.release_id
        or plan.release_sha256 != package.manifest_digest
        or plan.release_prefix != official.release_prefix_for(package.release_id)
    ):
        raise StateLawsPublicationPackageError(
            "publisher plan is not bound to the official State Laws release"
        )

    expected_descriptors = [
        *(dict(item) for item in package.artifact_descriptors),
        dict(package.manifest_descriptor),
    ]
    expected: list[tuple[str, int, str, str]] = []
    expected_paths: set[str] = set()
    for descriptor in expected_descriptors:
        relative = str(descriptor.get("relative_path") or "")
        if not relative or relative in expected_paths:
            raise StateLawsPublicationPackageError(
                "State Laws publication package has invalid descriptor paths"
            )
        expected_paths.add(relative)
        expected.append(
            (
                relative,
                int(descriptor.get("size_bytes", -1)),
                str(descriptor.get("sha256") or ""),
                f"{plan.release_prefix}/{relative}",
            )
        )
    expected_operations = tuple(sorted(expected))
    observed_operations = tuple(
        (item.relative_path, item.size_bytes, item.sha256, item.remote_path)
        for item in plan.operations
    )
    observed_relative_paths = [item.relative_path for item in plan.operations]
    if (
        len(observed_operations) != len(expected_operations)
        or len(observed_relative_paths) != len(set(observed_relative_paths))
        or observed_operations != expected_operations
    ):
        raise StateLawsPublicationPackageError(
            "publisher plan operations differ from the exact State Laws package"
        )


def _profile_digest(profile: HuggingFacePublicationProfile) -> str:
    return sha256(canonical_json_bytes(profile.to_dict())).hexdigest()


def require_state_laws_policy_binding(
    package: StateLawsPublicationPackage,
    request: LiveMutationRequest | Mapping[str, Any],
    *,
    plan: PublicationPlan,
    authorization: PublicationAuthorization | None = None,
    environ: Mapping[str, str] | None = None,
) -> StateLawsLivePolicyProof:
    """Seal an authorized request to one exact package and publisher plan.

    The proof grants no mutation on its own. The generic publisher reconstructs
    and re-evaluates it at the final boundary, and still requires its separate
    human :class:`PublicationApproval`.
    """

    if not isinstance(package, StateLawsPublicationPackage):
        raise StateLawsPublicationPackageError(
            "package must be a verified StateLawsPublicationPackage"
        )
    verify_state_laws_publication_package_identity(package)
    try:
        normalized = (
            request
            if isinstance(request, LiveMutationRequest)
            else LiveMutationRequest.from_mapping(request)
        )
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            "live mutation request is malformed"
        ) from exc
    if (
        normalized.final_manifest_digest != package.manifest_digest
        or normalized.dataset_repo_id != DEFAULT_DATASET_REPO_ID
        or set(normalized.jurisdictions)
        != set(CANONICAL_JURISDICTION_ORDER)
    ):
        raise StateLawsPublicationPackageError(
            "live mutation request is not bound to this exact publication package"
        )
    profile = state_laws_publication_profile()
    _verify_state_laws_plan_binding(package, plan, profile)
    if normalized.operation != "additive_main_upload" or normalized.phase != "main":
        raise StateLawsPublicationPackageError(
            "the generic State Laws main-branch commit requires a main-phase "
            "additive_main_upload authorization"
        )

    from ipfs_datasets_py.processors.legal_data import (
        state_laws_publication_policy as policy_module,
    )

    source_identity_before = _policy_verifier_source_identity()
    fresh_authorization, fixture_sha256, fixture_size = (
        _fresh_policy_authorization()
    )
    if (
        authorization is not None
        and canonical_json_bytes(authorization.to_dict())
        != canonical_json_bytes(fresh_authorization.to_dict())
    ):
        raise StateLawsPublicationPackageError(
            "caller authorization differs from the freshly reopened fixture"
        )
    try:
        decision = policy_module.require_live_mutation(
            normalized,
            authorization=fresh_authorization,
            environ=environ,
        )
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            f"State Laws live-mutation verifier refused the request: {exc}"
        ) from exc
    source_identity_after = _policy_verifier_source_identity()
    _, fixture_sha256_after, fixture_size_after = _fresh_policy_authorization()
    if (
        source_identity_before != source_identity_after
        or fixture_sha256 != fixture_sha256_after
        or fixture_size != fixture_size_after
    ):
        raise StateLawsPublicationPackageError(
            "State Laws policy source or authorization fixture changed during sealing"
        )

    request_payload = _canonical_mapping(
        normalized.to_dict(),
        label="live mutation request",
    )
    decision_payload = _canonical_mapping(
        decision.to_dict(),
        label="publication decision",
    )
    policy_identity = _canonical_mapping(
        source_identity_before,
        label="policy verifier identity",
    )
    from ipfs_datasets_py.huggingface.publisher import (
        _StateLawsLivePolicyBoundary,
    )

    final_boundary_identity = _canonical_mapping(
        _StateLawsLivePolicyBoundary.current_identities(),
        label="final publication boundary identity",
    )
    proof = StateLawsLivePolicyProof(
        schema_version=LIVE_POLICY_PROOF_SCHEMA_VERSION,
        profile_id=profile.profile_id,
        program_id=profile.program_id,
        profile_digest=_profile_digest(profile),
        plan_digest=plan.plan_digest,
        release_id=plan.release_id,
        manifest_digest=package.manifest_digest,
        release_digest=plan.release_sha256,
        repository_id=plan.repository_id,
        repository_type=plan.repository_type,
        target_revision=plan.target_revision,
        operation=normalized.operation,
        phase=str(normalized.phase),
        request=request_payload,
        request_digest=sha256(canonical_json_bytes(request_payload)).hexdigest(),
        decision=decision_payload,
        decision_digest=sha256(canonical_json_bytes(decision_payload)).hexdigest(),
        authorization_fixture_sha256=fixture_sha256,
        authorization_fixture_size_bytes=fixture_size,
        policy_verifier_identity=policy_identity,
        policy_verifier_identity_digest=sha256(
            canonical_json_bytes(policy_identity)
        ).hexdigest(),
        final_boundary_identity=final_boundary_identity,
        final_boundary_identity_digest=sha256(
            canonical_json_bytes(final_boundary_identity)
        ).hexdigest(),
    )
    return verify_state_laws_live_policy_proof(
        proof,
        plan=plan,
        profile=profile,
        local_root=package.output_root,
        final_boundary_identity=final_boundary_identity,
    )


def verify_state_laws_live_policy_proof(
    proof: StateLawsLivePolicyProof | Mapping[str, Any],
    *,
    plan: PublicationPlan,
    profile: HuggingFacePublicationProfile,
    local_root: str | Path,
    final_boundary_identity: Mapping[str, Any] | None = None,
) -> StateLawsLivePolicyProof:
    """Reopen all authority and re-evaluate a proof before any Hub call."""

    # Always round-trip even an existing instance. This detects mutation of a
    # nested list/dict retained behind its read-only top-level mapping.
    raw_proof = proof.to_dict() if isinstance(proof, StateLawsLivePolicyProof) else proof
    sealed = StateLawsLivePolicyProof.from_mapping(raw_proof)
    from ipfs_datasets_py.huggingface.publisher import (
        _StateLawsLivePolicyBoundary,
    )

    supplied_boundary_identity = _canonical_mapping(
        (
            final_boundary_identity
            if final_boundary_identity is not None
            else _StateLawsLivePolicyBoundary.current_identities()
        ),
        label="current final publication boundary identity",
    )
    current_boundary_identity = _canonical_mapping(
        _StateLawsLivePolicyBoundary.current_identities(),
        label="fresh final publication boundary identity",
    )
    if (
        supplied_boundary_identity != current_boundary_identity
        or current_boundary_identity != dict(sealed.final_boundary_identity)
        or sha256(canonical_json_bytes(current_boundary_identity)).hexdigest()
        != sealed.final_boundary_identity_digest
    ):
        raise StateLawsPublicationPackageError(
            "State Laws final publication boundary identity drifted after proof sealing"
        )
    official = state_laws_publication_profile()
    package = prepare_state_laws_publication_package(local_root)
    _verify_state_laws_plan_binding(package, plan, profile)
    if canonical_json_bytes(profile.to_dict()) != canonical_json_bytes(
        official.to_dict()
    ):
        raise StateLawsPublicationPackageError(
            "State Laws live publisher is not using the official profile"
        )
    expected_fields = {
        "profile_id": official.profile_id,
        "program_id": official.program_id,
        "profile_digest": _profile_digest(official),
        "plan_digest": plan.plan_digest,
        "release_id": plan.release_id,
        "manifest_digest": plan.release_sha256,
        "release_digest": plan.release_sha256,
        "repository_id": plan.repository_id,
        "repository_type": plan.repository_type,
        "target_revision": plan.target_revision,
        "operation": "additive_main_upload",
        "phase": "main",
    }
    mismatched = [
        name
        for name, expected in expected_fields.items()
        if getattr(sealed, name) != expected
    ]
    if mismatched:
        raise StateLawsPublicationPackageError(
            "State Laws live-policy proof does not match the publisher plan: "
            + ", ".join(mismatched)
        )
    if (
        plan.schema_version != STATE_LAWS_PLAN_SCHEMA
        or plan.metadata.get("profile_id") != official.profile_id
        or plan.metadata.get("program_id") != official.program_id
        or plan.metadata.get("goal_id") != official.goal_id
        or plan.repository_id != official.repository_id
        or plan.repository_type != official.repository_type
        or plan.target_revision != official.target_revision
        or plan.release_id != f"sha256-{plan.release_sha256}"
        or plan.release_prefix != official.release_prefix_for(plan.release_id)
    ):
        raise StateLawsPublicationPackageError(
            "State Laws publisher plan does not carry the official program identity"
        )

    from ipfs_datasets_py.processors.legal_data import (
        state_laws_publication_policy as policy_module,
    )

    source_identity_before = _policy_verifier_source_identity()
    if source_identity_before != dict(sealed.policy_verifier_identity):
        raise StateLawsPublicationPackageError(
            "State Laws policy verifier source identity drifted after proof sealing"
        )
    fresh_authorization, fixture_sha256, fixture_size = (
        _fresh_policy_authorization()
    )
    if (
        fixture_sha256 != sealed.authorization_fixture_sha256
        or fixture_size != sealed.authorization_fixture_size_bytes
    ):
        raise StateLawsPublicationPackageError(
            "State Laws publication authorization fixture drifted after proof sealing"
        )
    try:
        normalized = LiveMutationRequest.from_mapping(sealed.request)
        if (
            normalized.final_manifest_digest != plan.release_sha256
            or normalized.dataset_repo_id != plan.repository_id
            or normalized.operation != sealed.operation
            or normalized.phase != sealed.phase
        ):
            raise StateLawsPublicationPackageError(
                "State Laws proof request is not bound to the current publisher plan"
            )
        decision = policy_module.require_live_mutation(
            normalized,
            authorization=fresh_authorization,
            environ=None,
        )
    except StateLawsPublicationPackageError:
        raise
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            f"State Laws policy verifier refused the sealed request: {exc}"
        ) from exc
    decision_payload = _canonical_mapping(
        decision.to_dict(),
        label="fresh publication decision",
    )
    if (
        sha256(canonical_json_bytes(decision_payload)).hexdigest()
        != sealed.decision_digest
        or decision_payload != dict(sealed.decision)
        or decision.authorized is not True
    ):
        raise StateLawsPublicationPackageError(
            "State Laws policy decision differs from the sealed decision"
        )
    source_identity_after = _policy_verifier_source_identity()
    _, fixture_sha256_after, fixture_size_after = _fresh_policy_authorization()
    if (
        source_identity_after != source_identity_before
        or fixture_sha256_after != fixture_sha256
        or fixture_size_after != fixture_size
    ):
        raise StateLawsPublicationPackageError(
            "State Laws policy authority changed during final verification"
        )
    if (
        _canonical_mapping(
            _StateLawsLivePolicyBoundary.current_identities(),
            label="post-verification final publication boundary identity",
        )
        != current_boundary_identity
    ):
        raise StateLawsPublicationPackageError(
            "State Laws final publication boundary changed during verification"
        )
    return sealed


@dataclass(frozen=True, slots=True)
class StateLawsCanonicalControlBundle:
    """Local-only receipt for fixed canonical runtime control files."""

    candidate_path: str
    candidate_manifest_digest: str
    candidate_file_sha256: str
    dataset_card_path: str
    dataset_card_sha256: str
    release_manifest_digest: str
    seal_path: str
    seal_content_digest: str
    seal_file_sha256: str
    source_rights_receipt_digest: str
    staging_revision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_file_sha256": self.candidate_file_sha256,
            "candidate_manifest_digest": self.candidate_manifest_digest,
            "candidate_path": self.candidate_path,
            "dataset_card_path": self.dataset_card_path,
            "dataset_card_sha256": self.dataset_card_sha256,
            "hub_mutation_performed": False,
            "network_io_performed": False,
            "release_manifest_digest": self.release_manifest_digest,
            "seal_content_digest": self.seal_content_digest,
            "seal_file_sha256": self.seal_file_sha256,
            "seal_path": self.seal_path,
            "source_rights_receipt_digest": (
                self.source_rights_receipt_digest
            ),
            "staging_revision": self.staging_revision,
        }


def _canonical_control_receipt(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], str, bytes]:
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as canonical_runtime,
    )

    body = _canonical_mapping(payload, label="canonical control receipt")
    body.pop("canonical_digest", None)
    body.pop("content_digest", None)
    digest = canonical_runtime.canonical_no_self_field_digest(body)
    body["canonical_digest"] = digest
    body["content_digest"] = digest
    encoded = canonical_json_bytes(body) + b"\n"
    return body, digest, encoded


def _open_fixed_control_parent(root_fd: int, relative_path: str) -> tuple[int, str]:
    parts = relative_path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise StateLawsPublicationPackageError(
            f"unsafe canonical control path: {relative_path!r}"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            next_descriptor = os.open(
                component,
                flags,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as exc:
        os.close(descriptor)
        raise StateLawsPublicationPackageError(
            "canonical control parent is missing, unsafe, or a symlink: "
            f"{relative_path}: {exc}"
        ) from exc
    return descriptor, parts[-1]


def _atomic_write_canonical_controls(
    repository_root: str | Path,
    files: Mapping[str, bytes],
) -> None:
    """Stage fixed files through anchored dirfds and atomically replace each."""

    from ipfs_datasets_py.huggingface.publisher import (
        _open_absolute_path_nofollow_components,
    )

    try:
        _, root_fd = _open_absolute_path_nofollow_components(
            repository_root,
            label="canonical controls repository_root",
            require_directory=True,
        )
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            f"cannot open canonical controls repository root safely: {exc}"
        ) from exc

    staged: list[tuple[int, str, str, bytes, tuple[int, int] | None]] = []
    try:
        for relative_path, encoded in sorted(files.items()):
            parent_fd, target_name = _open_fixed_control_parent(
                root_fd,
                relative_path,
            )
            try:
                before = os.stat(
                    target_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                before_identity = None
            except OSError as exc:
                os.close(parent_fd)
                raise StateLawsPublicationPackageError(
                    f"cannot inspect canonical control target {relative_path}: {exc}"
                ) from exc
            else:
                if not stat.S_ISREG(before.st_mode):
                    os.close(parent_fd)
                    raise StateLawsPublicationPackageError(
                        "canonical control target must be absent or a regular "
                        f"file: {relative_path}"
                    )
                before_identity = (before.st_dev, before.st_ino)

            temporary_name = ""
            temporary_fd = -1
            for _ in range(32):
                candidate = (
                    f".{target_name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
                )
                try:
                    temporary_fd = os.open(
                        candidate,
                        os.O_RDWR
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0)
                        | getattr(os, "O_CLOEXEC", 0),
                        0o600,
                        dir_fd=parent_fd,
                    )
                except FileExistsError:
                    continue
                temporary_name = candidate
                break
            if temporary_fd < 0:
                os.close(parent_fd)
                raise StateLawsPublicationPackageError(
                    f"cannot allocate atomic control tempfile for {relative_path}"
                )
            try:
                view = memoryview(encoded)
                written = 0
                while written < len(view):
                    count = os.write(temporary_fd, view[written:])
                    if count <= 0:
                        raise OSError("short atomic control write")
                    written += count
                os.fchmod(temporary_fd, 0o644)
                os.fsync(temporary_fd)
                os.lseek(temporary_fd, 0, os.SEEK_SET)
                observed = bytearray()
                while True:
                    chunk = os.read(temporary_fd, 1024 * 1024)
                    if not chunk:
                        break
                    observed.extend(chunk)
                if bytes(observed) != encoded:
                    raise StateLawsPublicationPackageError(
                        f"atomic control tempfile verification failed: {relative_path}"
                    )
            except Exception:
                os.close(temporary_fd)
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except OSError:
                    pass
                os.close(parent_fd)
                raise
            os.close(temporary_fd)
            staged.append(
                (
                    parent_fd,
                    temporary_name,
                    target_name,
                    encoded,
                    before_identity,
                )
            )

        for parent_fd, _, target_name, _, before_identity in staged:
            try:
                current = os.stat(
                    target_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                current_identity = None
            else:
                if not stat.S_ISREG(current.st_mode):
                    raise StateLawsPublicationPackageError(
                        "canonical control target changed to an unsafe file type"
                    )
                current_identity = (current.st_dev, current.st_ino)
            if current_identity != before_identity:
                raise StateLawsPublicationPackageError(
                    "canonical control target changed during atomic staging"
                )

        for parent_fd, temporary_name, target_name, encoded, _ in staged:
            os.replace(
                temporary_name,
                target_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            descriptor = os.open(
                target_name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
            try:
                observed = bytearray()
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    observed.extend(chunk)
                if bytes(observed) != encoded:
                    raise StateLawsPublicationPackageError(
                        "canonical control bytes changed during atomic replace"
                    )
            finally:
                os.close(descriptor)
            os.fsync(parent_fd)
    except OSError as exc:
        raise StateLawsPublicationPackageError(
            f"atomic canonical control write failed: {exc}"
        ) from exc
    finally:
        for parent_fd, temporary_name, _, _, _ in staged:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            os.close(parent_fd)
        os.close(root_fd)


def materialize_state_laws_canonical_controls(
    package: StateLawsPublicationPackage,
    plan: PublicationPlan,
    live_policy_proof: StateLawsLivePolicyProof | Mapping[str, Any],
    *,
    repository_root: str | Path,
    sealed_at: str,
) -> StateLawsCanonicalControlBundle:
    """Materialize canonical candidate/card/seal files without network I/O."""

    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as canonical_runtime,
    )
    from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
        LIVE_COMPLIANCE_REPORT_SCHEMA,
    )

    verify_state_laws_publication_package_identity(package)
    profile = state_laws_publication_profile()
    _verify_state_laws_plan_binding(package, plan, profile)
    sealed = verify_state_laws_live_policy_proof(
        live_policy_proof,
        plan=plan,
        profile=profile,
        local_root=package.output_root,
    )
    if sealed.authorized is not True:
        raise StateLawsPublicationPackageError(
            "canonical controls require an authorized live policy proof"
        )

    manifest_bytes = _read_regular_file_nofollow(
        package.manifest_path,
        label="State Laws release manifest",
        maximum_bytes=64 * 1024 * 1024,
    )
    try:
        manifest = json.loads(
            manifest_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            "State Laws release manifest is malformed"
        ) from exc
    if not isinstance(manifest, Mapping):
        raise StateLawsPublicationPackageError(
            "State Laws release manifest must be an object"
        )
    release_point = str(manifest.get("release_point") or "").casefold()
    mode = str(manifest.get("mode") or "").casefold()
    if (
        manifest.get("fixture_only") is True
        or "fixture" in release_point
        or mode in {"fixture", "fixture_only", "test"}
    ):
        raise StateLawsPublicationPackageError(
            "fixture State Laws releases cannot produce canonical controls"
        )
    validate_exact_51_coverage(manifest.get("jurisdictions") or ())

    package_rights_path = Path(package.output_root) / SOURCE_RIGHTS_RECEIPT_RELPATH
    repository_rights_path = Path(repository_root) / SOURCE_RIGHTS_RECEIPT_RELPATH
    package_rights_bytes = _read_regular_file_nofollow(
        package_rights_path,
        label="packaged State Laws source-rights receipt",
        maximum_bytes=16 * 1024 * 1024,
    )
    repository_rights_bytes = _read_regular_file_nofollow(
        repository_rights_path,
        label="canonical State Laws source-rights receipt",
        maximum_bytes=16 * 1024 * 1024,
    )
    if package_rights_bytes != repository_rights_bytes:
        raise StateLawsPublicationPackageError(
            "packaged and canonical source-rights receipt bytes differ"
        )
    try:
        rights = json.loads(
            repository_rights_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            "canonical source-rights receipt is malformed"
        ) from exc
    if not isinstance(rights, Mapping):
        raise StateLawsPublicationPackageError(
            "canonical source-rights receipt must be an object"
        )
    require_live_source_rights_receipt(rights)
    if (
        rights.get("report_schema") != LIVE_COMPLIANCE_REPORT_SCHEMA
        or rights.get("authorizing_for_publication") is not True
        or rights.get("status") != "passed"
        or rights.get("mode") != "live"
        or rights.get("evidence_mode") != "live"
        or rights.get("fixture_only_non_authorizing") is not False
    ):
        raise StateLawsPublicationPackageError(
            "canonical source-rights receipt is fixture or non-authorizing"
        )
    rights_digest = _require_sha256(
        rights.get("report_digest_sha256"),
        label="canonical source-rights receipt digest",
    )
    rights_body = dict(rights)
    rights_body.pop("report_digest_sha256", None)
    if sha256(canonical_json_bytes(rights_body)).hexdigest() != rights_digest:
        raise StateLawsPublicationPackageError(
            "canonical source-rights receipt digest does not match its body"
        )
    admitted_ids = tuple(
        str(item)
        for item in (
            (manifest.get("source_rights_receipt") or {}).get(
                "admitted_record_ids"
            )
            or ()
        )
    )
    if len(admitted_ids) != 51 or not set(admitted_ids).issubset(
        set(str(item) for item in rights.get("admitted_record_ids") or ())
    ):
        raise StateLawsPublicationPackageError(
            "canonical source-rights receipt does not bind exact-51 admitted "
            "State statutory-text records"
        )
    catalog_digest = _require_sha256(
        rights.get("catalog_digest_sha256"),
        label="canonical source-rights catalog digest",
    )

    request = dict(sealed.request)
    staging_revision = str(request.get("staging_revision") or "")
    canonical_runtime.require_immutable_revision(
        staging_revision,
        name="State Laws staging revision",
    )
    if (
        request.get("staging_canary_passed") is not True
        or request.get("staging_redownload_verified") is not True
        or request.get("authorize_mutation") is not True
    ):
        raise StateLawsPublicationPackageError(
            "canonical controls require an authorizing verified staging canary"
        )
    canonical_runtime.parse_utc_z(sealed_at, name="sealed_at")

    candidate_payload = {
        "admitted_source_ids": list(admitted_ids),
        "artifact_count": len(plan.operations),
        "authorizing_for_publication": True,
        "dataset_repo_id": plan.repository_id,
        "dirty": False,
        "fixture_only": False,
        "jurisdiction_codes": list(CANONICAL_JURISDICTION_ORDER),
        "jurisdiction_count": 51,
        "manifest_digest": plan.release_sha256,
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": sealed.proof_digest,
        "release_id": plan.release_id,
        "release_prefix": plan.release_prefix,
        "schema": canonical_runtime.MANIFEST_SCHEMA_V1,
        "source_rights_catalog_digest": catalog_digest,
        "source_rights_receipt_digest": rights_digest,
        "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        "status": "passed",
    }
    candidate, candidate_digest, _ = _canonical_control_receipt(
        candidate_payload
    )
    # The generic gate uses final_manifest_digest for the candidate-control
    # identity and reserves top-level manifest_digest for the release artifact
    # binding. Both are no-self fields, so adding the explicit control identity
    # does not create a hash cycle.
    candidate["final_manifest_digest"] = candidate_digest
    candidate_bytes = canonical_json_bytes(candidate) + b"\n"
    card_bytes = (
        "# State Laws immutable release\n\n"
        f"Release manifest digest: `{plan.release_sha256}`\n\n"
        "Canonical source-rights compliance digest: "
        f"`{rights_digest}`\n\n"
        "Coverage: exact 51 U.S. state-level jurisdictions.\n"
    ).encode("utf-8")
    seal_payload = {
        "created_after_mutation": False,
        "dataset_repo_id": plan.repository_id,
        "dirty": False,
        "final_manifest_digest": candidate_digest,
        "fixture_only": False,
        "manifest_digest": candidate_digest,
        "operation": "additive_main_upload",
        "phase": "state_main",
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": sealed.proof_digest,
        "post_hoc": False,
        "present": True,
        "release_manifest_digest": plan.release_sha256,
        "schema": canonical_runtime.SEAL_SCHEMA_V1,
        "sealed_at": sealed_at,
        "staging_revision": staging_revision,
        "status": "sealed",
        "timing": "before_mutation",
    }
    _, seal_digest, seal_bytes = _canonical_control_receipt(seal_payload)
    files = {
        canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH: candidate_bytes,
        canonical_runtime.STATE_DATASET_CARD_RELPATH: card_bytes,
        canonical_runtime.STATE_PREPUBLICATION_SEAL_RELPATH: seal_bytes,
    }
    _atomic_write_canonical_controls(repository_root, files)
    return StateLawsCanonicalControlBundle(
        candidate_path=canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH,
        candidate_manifest_digest=candidate_digest,
        candidate_file_sha256=sha256(candidate_bytes).hexdigest(),
        dataset_card_path=canonical_runtime.STATE_DATASET_CARD_RELPATH,
        dataset_card_sha256=sha256(card_bytes).hexdigest(),
        release_manifest_digest=plan.release_sha256,
        seal_path=canonical_runtime.STATE_PREPUBLICATION_SEAL_RELPATH,
        seal_content_digest=seal_digest,
        seal_file_sha256=sha256(seal_bytes).hexdigest(),
        source_rights_receipt_digest=rights_digest,
        staging_revision=staging_revision,
    )


class _StateLawsLivePolicyProofVerifier:
    """Stable executable target for the final generic publisher dispatch."""

    EXECUTABLE_IMPORT_SHA256 = {}

    @staticmethod
    def _function_sha256(target):
        hashlib_module = __import__("hashlib")
        json_module = __import__("json")

        from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
            _loaded_function_projection,
        )

        projection = _loaded_function_projection(
            target,
            _include_global_bindings=False,
        )
        return getattr(hashlib_module, "sha256")(
            getattr(json_module, "dumps")(
                projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def current_executable_identities(cls):
        from ipfs_datasets_py.processors.legal_data import (
            state_laws_publication_package as package_module,
        )

        names = (
            "_canonical_mapping",
            "_fresh_policy_authorization",
            "_policy_verifier_source_identity",
            "_verify_state_laws_plan_binding",
            "prepare_state_laws_publication_package",
            "state_laws_publication_profile",
            "verify_state_laws_live_policy_proof",
        )
        return {
            name: cls._function_sha256(getattr(package_module, name))
            for name in names
        }

    @staticmethod
    def verify(
        proof,
        *,
        plan,
        profile,
        local_root,
        final_boundary_identity=None,
    ):
        from ipfs_datasets_py.processors.legal_data import (
            state_laws_publication_package as package_module,
        )

        verifier_class = getattr(
            package_module,
            "_StateLawsLivePolicyProofVerifier",
        )
        current = verifier_class.current_executable_identities()
        if current != dict(
            verifier_class.EXECUTABLE_IMPORT_SHA256
        ):
            error_type = getattr(
                package_module,
                "StateLawsPublicationPackageError",
            )
            raise error_type(
                "State Laws package verifier executable identity drifted"
            )
        verifier = getattr(
            package_module,
            "verify_state_laws_live_policy_proof",
        )
        return verifier(
            proof,
            plan=plan,
            profile=profile,
            local_root=local_root,
            final_boundary_identity=final_boundary_identity,
        )


_StateLawsLivePolicyProofVerifier.EXECUTABLE_IMPORT_SHA256 = MappingProxyType(
    _StateLawsLivePolicyProofVerifier.current_executable_identities()
)


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "DRY_RUN_SCHEMA_VERSION",
    "LIVE_POLICY_PROOF_SCHEMA_VERSION",
    "PERFORMS_NETWORK_IO",
    "REENCODES_PHYSICAL_ARTIFACTS",
    "SCHEMA_VERSION",
    "STATE_LAWS_PLAN_SCHEMA",
    "STATE_LAWS_PROFILE_ID",
    "STATE_LAWS_RECEIPT_SCHEMA",
    "StateLawsCanonicalControlBundle",
    "StateLawsPublicationDryRun",
    "StateLawsLivePolicyProof",
    "StateLawsPublicationPackage",
    "StateLawsPublicationPackageError",
    "materialize_state_laws_canonical_controls",
    "plan_state_laws_publication_dry_run",
    "prepare_state_laws_publication_package",
    "require_state_laws_policy_binding",
    "state_laws_publication_profile",
    "verify_state_laws_live_policy_proof",
    "verify_state_laws_publication_package_identity",
]
