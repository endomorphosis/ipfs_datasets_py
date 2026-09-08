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
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
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
    PUBLICATION_PARENT_REVISION,
    REQUIRED_LIVE_MUTATION_GATES,
    LiveMutationRequest,
    PublicationAuthorization,
    assert_historical_baseline_pin_preserved,
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
    VIEWER_DEFAULT_CONFIG_NAME,
    VIEWER_LEGACY_CONFIG_NAME,
    digest_mapping,
    render_state_laws_root_viewer_card,
    state_laws_root_viewer_configs,
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
STATE_LAWS_STAGING_UPLOAD_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/staging_upload.json"
)
STATE_LAWS_STAGING_CANARY_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/staging_canary.json"
)

VIEWER_CONTROL_SCHEMA_VERSION: Final = "state-laws-viewer-control-plan/v1"
VIEWER_CONTROL_AUTHORIZATION_SCHEMA_VERSION: Final = (
    "state-laws-viewer-control-replacement-authorization/v1"
)
VIEWER_ROOT_PATH: Final = "README.md"
VIEWER_CONTROL_OBSERVE: Final = "observe_root_control"
VIEWER_CONTROL_ADD: Final = "add_root_control_if_absent"
VIEWER_CONTROL_SKIP: Final = "skip_identical_root_control"
VIEWER_CONTROL_REPLACE: Final = "replace_root_control_if_digest_matches"

DEFAULT_CONFIG_NAME: Final = VIEWER_DEFAULT_CONFIG_NAME
LEGACY_CONFIG_NAME: Final = VIEWER_LEGACY_CONFIG_NAME

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False
REENCODES_PHYSICAL_ARTIFACTS: Final = False

class StateLawsPublicationPackageError(ValueError):
    """Raised when a local release cannot be planned without weakening it."""


@dataclass(frozen=True, slots=True)
class StateLawsViewerControlAuthorization:
    """Review binding for one exact root ``README.md`` CAS replacement."""

    review_id: str
    reviewer: str
    repository_id: str
    target_revision: str
    audited_parent_commit: str
    release_manifest_digest: str
    expected_existing_sha256: str
    replacement_sha256: str
    remote_path: str = VIEWER_ROOT_PATH
    operation: str = VIEWER_CONTROL_REPLACE
    schema_version: str = VIEWER_CONTROL_AUTHORIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != VIEWER_CONTROL_AUTHORIZATION_SCHEMA_VERSION:
            raise StateLawsPublicationPackageError(
                "unsupported Viewer-control replacement authorization schema"
            )
        if self.operation != VIEWER_CONTROL_REPLACE:
            raise StateLawsPublicationPackageError(
                "Viewer-control authorization only permits digest-matched replacement"
            )
        if self.remote_path != VIEWER_ROOT_PATH:
            raise StateLawsPublicationPackageError(
                "Viewer-control authorization must target root README.md"
            )
        if self.repository_id != DEFAULT_DATASET_REPO_ID:
            raise StateLawsPublicationPackageError(
                "Viewer-control authorization targets the wrong dataset repository"
            )
        if self.target_revision != "main":
            raise StateLawsPublicationPackageError(
                "Viewer-control replacement authorization must target main"
            )
        parent = str(self.audited_parent_commit or "")
        if (
            len(parent) != 40
            or parent != parent.casefold()
            or any(character not in "0123456789abcdef" for character in parent)
        ):
            raise StateLawsPublicationPackageError(
                "Viewer-control authorization requires an exact audited parent commit"
            )
        for field_name in (
            "release_manifest_digest",
            "expected_existing_sha256",
            "replacement_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), label=field_name),
            )
        for field_name in ("review_id", "reviewer"):
            value = str(getattr(self, field_name) or "")
            if not value or value.strip() != value:
                raise StateLawsPublicationPackageError(
                    f"Viewer-control authorization {field_name} is required"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audited_parent_commit": self.audited_parent_commit,
            "expected_existing_sha256": self.expected_existing_sha256,
            "operation": self.operation,
            "release_manifest_digest": self.release_manifest_digest,
            "remote_path": self.remote_path,
            "replacement_sha256": self.replacement_sha256,
            "repository_id": self.repository_id,
            "review_id": self.review_id,
            "reviewer": self.reviewer,
            "schema_version": self.schema_version,
            "target_revision": self.target_revision,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "StateLawsViewerControlAuthorization":
        if not isinstance(value, Mapping):
            raise StateLawsPublicationPackageError(
                "Viewer-control replacement authorization must be an object"
            )
        allowed = {
            "audited_parent_commit",
            "expected_existing_sha256",
            "operation",
            "release_manifest_digest",
            "remote_path",
            "replacement_sha256",
            "repository_id",
            "review_id",
            "reviewer",
            "schema_version",
            "target_revision",
        }
        if set(value) != allowed:
            raise StateLawsPublicationPackageError(
                "Viewer-control replacement authorization fields differ from "
                "the sealed schema"
            )
        return cls(**{name: value[name] for name in allowed})


@dataclass(frozen=True, slots=True)
class StateLawsViewerControlPlan:
    """Exact root-card intent kept separate from immutable release adds."""

    repository_id: str
    target_revision: str
    audited_parent_commit: str
    release_prefix: str
    release_manifest_digest: str
    sha256: str
    size_bytes: int
    configs: tuple[Mapping[str, Any], ...]
    existing_state: str
    operation: str
    expected_existing_sha256: str = ""
    replacement_review: Mapping[str, Any] | None = None
    remote_path: str = VIEWER_ROOT_PATH
    schema_version: str = VIEWER_CONTROL_SCHEMA_VERSION
    plan_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != VIEWER_CONTROL_SCHEMA_VERSION:
            raise StateLawsPublicationPackageError(
                "unsupported State Laws Viewer-control plan schema"
            )
        if self.repository_id != DEFAULT_DATASET_REPO_ID:
            raise StateLawsPublicationPackageError(
                "Viewer-control plan targets the wrong repository"
            )
        if self.remote_path != VIEWER_ROOT_PATH:
            raise StateLawsPublicationPackageError(
                "Viewer-control plan must target root README.md"
            )
        digest = _require_sha256(self.sha256, label="Viewer-control sha256")
        release_digest = _require_sha256(
            self.release_manifest_digest,
            label="Viewer-control release_manifest_digest",
        )
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise StateLawsPublicationPackageError(
                "Viewer-control size_bytes must be a non-negative integer"
            )
        if self.size_bytes < 0:
            raise StateLawsPublicationPackageError(
                "Viewer-control size_bytes must be a non-negative integer"
            )
        configs = tuple(
            MappingProxyType(_canonical_mapping(item, label="Viewer config"))
            for item in self.configs
        )
        if not configs:
            raise StateLawsPublicationPackageError(
                "Viewer-control plan requires exact config controls"
            )
        if self.existing_state not in {"unobserved", "absent", "present"}:
            raise StateLawsPublicationPackageError(
                "Viewer-control existing_state is invalid"
            )
        if self.operation not in {
            VIEWER_CONTROL_OBSERVE,
            VIEWER_CONTROL_ADD,
            VIEWER_CONTROL_SKIP,
            VIEWER_CONTROL_REPLACE,
        }:
            raise StateLawsPublicationPackageError(
                "Viewer-control operation is invalid"
            )
        expected_existing = str(self.expected_existing_sha256 or "")
        if expected_existing:
            expected_existing = _require_sha256(
                expected_existing,
                label="Viewer-control expected_existing_sha256",
            )
        authorization = (
            None
            if self.replacement_review is None
            else MappingProxyType(
                _canonical_mapping(
                    self.replacement_review,
                    label="Viewer-control replacement authorization",
                )
            )
        )
        if self.operation == VIEWER_CONTROL_REPLACE and authorization is None:
            raise StateLawsPublicationPackageError(
                "Viewer-control replacement lacks exact review authorization"
            )
        if self.operation != VIEWER_CONTROL_REPLACE and authorization is not None:
            raise StateLawsPublicationPackageError(
                "Viewer-control authorization is only valid for replacement"
            )
        if authorization is not None:
            review = StateLawsViewerControlAuthorization.from_mapping(authorization)
            expected_review = {
                "audited_parent_commit": self.audited_parent_commit,
                "expected_existing_sha256": expected_existing,
                "release_manifest_digest": release_digest,
                "remote_path": self.remote_path,
                "replacement_sha256": digest,
                "repository_id": self.repository_id,
                "target_revision": self.target_revision,
            }
            if any(
                review.to_dict().get(key) != value
                for key, value in expected_review.items()
            ):
                raise StateLawsPublicationPackageError(
                    "Viewer-control replacement review binding drifted"
                )
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "release_manifest_digest", release_digest)
        object.__setattr__(self, "configs", configs)
        object.__setattr__(self, "expected_existing_sha256", expected_existing)
        object.__setattr__(self, "replacement_review", authorization)
        identity = self._identity_payload()
        computed = sha256(canonical_json_bytes(identity)).hexdigest()
        if self.plan_digest and self.plan_digest != computed:
            raise StateLawsPublicationPackageError(
                "Viewer-control plan digest mismatch"
            )
        object.__setattr__(self, "plan_digest", computed)

    def _identity_payload(self) -> dict[str, Any]:
        replaces_root = self.operation == VIEWER_CONTROL_REPLACE
        supported = self.operation in {
            VIEWER_CONTROL_ADD,
            VIEWER_CONTROL_REPLACE,
            VIEWER_CONTROL_SKIP,
        }
        return {
            "audited_parent_commit": self.audited_parent_commit,
            "canonical_writer_supports_operation": supported,
            "configs": [dict(item) for item in self.configs],
            "default_config": DEFAULT_CONFIG_NAME,
            "existing_state": self.existing_state,
            "expected_existing_sha256": self.expected_existing_sha256 or None,
            "immutable_release_artifacts_additive_only": True,
            "jurisdiction_count": len(CANONICAL_JURISDICTION_ORDER),
            "legacy_config": LEGACY_CONFIG_NAME,
            "legacy_root_objects_preserved": True,
            "operation": self.operation,
            "release_manifest_digest": self.release_manifest_digest,
            "release_prefix": self.release_prefix,
            "remote_path": self.remote_path,
            "replacement_review": (
                dict(self.replacement_review)
                if self.replacement_review is not None
                else None
            ),
            "repository_id": self.repository_id,
            "requires_root_control_plane_write": self.operation
            in {VIEWER_CONTROL_ADD, VIEWER_CONTROL_REPLACE},
            "replaces_existing_root": replaces_root,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "target_revision": self.target_revision,
            "whole_publication_additive_only": self.operation
            in {VIEWER_CONTROL_ADD, VIEWER_CONTROL_SKIP},
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity_payload(), "plan_digest": self.plan_digest}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StateLawsViewerControlPlan":
        if not isinstance(value, Mapping):
            raise StateLawsPublicationPackageError(
                "Viewer-control plan must be an object"
            )
        required = {
            "audited_parent_commit",
            "configs",
            "existing_state",
            "expected_existing_sha256",
            "operation",
            "plan_digest",
            "release_manifest_digest",
            "release_prefix",
            "remote_path",
            "replacement_review",
            "repository_id",
            "schema_version",
            "sha256",
            "size_bytes",
            "target_revision",
        }
        if not required.issubset(value):
            raise StateLawsPublicationPackageError(
                "Viewer-control plan omits required fields"
            )
        plan = cls(
            repository_id=value["repository_id"],
            target_revision=value["target_revision"],
            audited_parent_commit=value["audited_parent_commit"],
            release_prefix=value["release_prefix"],
            release_manifest_digest=value["release_manifest_digest"],
            sha256=value["sha256"],
            size_bytes=value["size_bytes"],
            configs=tuple(value["configs"]),
            existing_state=value["existing_state"],
            operation=value["operation"],
            expected_existing_sha256=(
                value.get("expected_existing_sha256") or ""
            ),
            replacement_review=value.get("replacement_review"),
            remote_path=value["remote_path"],
            schema_version=value["schema_version"],
            plan_digest=value["plan_digest"],
        )
        if canonical_json_bytes(plan.to_dict()) != canonical_json_bytes(dict(value)):
            raise StateLawsPublicationPackageError(
                "Viewer-control plan contains unexpected or derived-field drift"
            )
        return plan


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


def state_laws_staging_publication_profile(
    staging_branch: str,
) -> HuggingFacePublicationProfile:
    """Validate a staging ref and return the immutable State Laws identity.

    The branch itself is carried by the digest-bound ``PublicationPlan``;
    profile identity remains byte-for-byte identical between staging and main.
    """

    branch = str(staging_branch or "").strip()
    if (
        not branch
        or branch == "main"
        or len(branch) > 128
        or branch.startswith(("-", ".", "/"))
        or branch.endswith((".", "/", ".lock"))
        or ".." in branch
        or "@{" in branch
        or any(character in branch for character in " ~^:?*[\\")
    ):
        raise StateLawsPublicationPackageError(
            "State Laws staging branch is not a safe dedicated Git revision"
        )
    return state_laws_publication_profile()


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


def state_laws_viewer_control_card_bytes(
    package: StateLawsPublicationPackage,
    *,
    release_prefix: str,
) -> bytes:
    """Render the exact repository-root card for one verified release."""

    verify_state_laws_publication_package_identity(package)
    expected_prefix = STATE_LAWS_RELEASE_PREFIX_TEMPLATE.format(
        release_id=package.release_id
    )
    if release_prefix != expected_prefix:
        raise StateLawsPublicationPackageError(
            "Viewer root card release prefix differs from the verified package"
        )
    corpus_paths = tuple(
        str(item.get("relative_path") or "")
        for item in package.artifact_descriptors
        if str(item.get("relative_path") or "").startswith("data/corpus/")
        and str(item.get("relative_path") or "").endswith(".parquet")
    )
    if not corpus_paths:
        raise StateLawsPublicationPackageError(
            "Viewer root card requires combined corpus Parquet artifacts"
        )
    rights_bytes = _read_regular_file_nofollow(
        Path(package.output_root) / SOURCE_RIGHTS_RECEIPT_RELPATH,
        label="packaged source-rights receipt for Viewer control",
        maximum_bytes=16 * 1024 * 1024,
    )
    try:
        rights = json.loads(
            rights_bytes.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            "packaged source-rights receipt for Viewer control is malformed"
        ) from exc
    if not isinstance(rights, Mapping):
        raise StateLawsPublicationPackageError(
            "packaged source-rights receipt for Viewer control must be an object"
        )
    rights_digest = _require_sha256(
        rights.get("report_digest_sha256")
        or rights.get("receipt_digest")
        or rights.get("content_digest"),
        label="Viewer-control source-rights receipt digest",
    )
    try:
        rendered = render_state_laws_root_viewer_card(
            release_prefix=release_prefix,
            release_manifest_digest=package.manifest_digest,
            source_rights_receipt_digest=rights_digest,
        )
    except Exception as exc:
        raise StateLawsPublicationPackageError(
            f"cannot render exact root Viewer control: {exc}"
        ) from exc
    return rendered.encode("utf-8")


def plan_state_laws_viewer_control(
    package: StateLawsPublicationPackage,
    plan: PublicationPlan,
    *,
    root_readme_exists: bool | None = None,
    existing_root_readme_sha256: str | None = None,
    replacement_authorization: (
        StateLawsViewerControlAuthorization | Mapping[str, Any] | None
    ) = None,
) -> StateLawsViewerControlPlan:
    """Plan root Viewer metadata without conflating it with release adds.

    ``root_readme_exists=None`` means the remote root has not been observed and
    yields a non-executable observation requirement.  A present, differing
    root is a hard conflict unless an exact digest-bound replacement review is
    supplied.
    """

    verify_state_laws_publication_package_identity(package)
    if not isinstance(plan, PublicationPlan):
        raise StateLawsPublicationPackageError(
            "Viewer-control planning requires a PublicationPlan"
        )
    if (
        plan.repository_id != DEFAULT_DATASET_REPO_ID
        or plan.release_id != package.release_id
        or plan.release_sha256 != package.manifest_digest
        or plan.release_prefix
        != STATE_LAWS_RELEASE_PREFIX_TEMPLATE.format(release_id=package.release_id)
    ):
        raise StateLawsPublicationPackageError(
            "Viewer-control planning is not bound to the exact State Laws release"
        )
    card_bytes = state_laws_viewer_control_card_bytes(
        package,
        release_prefix=plan.release_prefix,
    )
    card_sha256 = sha256(card_bytes).hexdigest()
    configs = tuple(
        MappingProxyType(dict(config))
        for config in state_laws_root_viewer_configs(plan.release_prefix)
    )
    observed_digest = str(existing_root_readme_sha256 or "")
    if observed_digest:
        observed_digest = _require_sha256(
            observed_digest,
            label="existing root README sha256",
        )
        if root_readme_exists is False:
            raise StateLawsPublicationPackageError(
                "root README cannot be both absent and digest-observed"
            )
        root_readme_exists = True
    if root_readme_exists not in {None, True, False}:
        raise StateLawsPublicationPackageError(
            "root_readme_exists must be true, false, or unobserved"
        )
    if root_readme_exists is True and not observed_digest:
        raise StateLawsPublicationPackageError(
            "present root README requires its observed SHA-256 digest"
        )

    authorization: StateLawsViewerControlAuthorization | None
    if replacement_authorization is None:
        authorization = None
    elif isinstance(
        replacement_authorization,
        StateLawsViewerControlAuthorization,
    ):
        authorization = replacement_authorization
    else:
        authorization = StateLawsViewerControlAuthorization.from_mapping(
            replacement_authorization
        )

    if root_readme_exists is None:
        existing_state = "unobserved"
        operation = VIEWER_CONTROL_OBSERVE
    elif root_readme_exists is False:
        existing_state = "absent"
        operation = VIEWER_CONTROL_ADD
    elif observed_digest == card_sha256:
        existing_state = "present"
        operation = VIEWER_CONTROL_SKIP
    else:
        existing_state = "present"
        operation = VIEWER_CONTROL_REPLACE

    if operation != VIEWER_CONTROL_REPLACE and authorization is not None:
        raise StateLawsPublicationPackageError(
            "replacement authorization supplied when no replacement is needed"
        )
    if operation == VIEWER_CONTROL_REPLACE:
        if authorization is None:
            raise StateLawsPublicationPackageError(
                "existing root README conflicts with the exact Viewer control; "
                "an exact digest-bound replacement authorization is required"
            )
        expected_authorization = {
            "audited_parent_commit": plan.audited_parent_commit,
            "expected_existing_sha256": observed_digest,
            "operation": VIEWER_CONTROL_REPLACE,
            "release_manifest_digest": package.manifest_digest,
            "remote_path": VIEWER_ROOT_PATH,
            "replacement_sha256": card_sha256,
            "repository_id": plan.repository_id,
            "target_revision": plan.target_revision,
        }
        actual_authorization = authorization.to_dict()
        if any(
            actual_authorization.get(key) != value
            for key, value in expected_authorization.items()
        ):
            raise StateLawsPublicationPackageError(
                "Viewer-control replacement authorization differs from the "
                "observed root, replacement, parent, or release"
            )

    control = StateLawsViewerControlPlan(
        repository_id=plan.repository_id,
        target_revision=plan.target_revision,
        audited_parent_commit=plan.audited_parent_commit,
        release_prefix=plan.release_prefix,
        release_manifest_digest=package.manifest_digest,
        sha256=card_sha256,
        size_bytes=len(card_bytes),
        configs=configs,
        existing_state=existing_state,
        operation=operation,
        expected_existing_sha256=observed_digest,
        replacement_review=(
            authorization.to_dict() if authorization is not None else None
        ),
    )
    return verify_state_laws_viewer_control_plan(package, plan, control)


def verify_state_laws_viewer_control_plan(
    package: StateLawsPublicationPackage,
    plan: PublicationPlan,
    control: StateLawsViewerControlPlan | Mapping[str, Any] | None = None,
) -> StateLawsViewerControlPlan:
    """Recompute and verify the exact Viewer controls carried by a plan."""

    verify_state_laws_publication_package_identity(package)
    raw = plan.metadata.get("viewer_control") if control is None else control
    resolved = (
        raw
        if isinstance(raw, StateLawsViewerControlPlan)
        else StateLawsViewerControlPlan.from_mapping(raw)
    )
    card_bytes = state_laws_viewer_control_card_bytes(
        package,
        release_prefix=plan.release_prefix,
    )
    expected_configs = [
        dict(config) for config in state_laws_root_viewer_configs(plan.release_prefix)
    ]
    if (
        resolved.repository_id != plan.repository_id
        or resolved.target_revision != plan.target_revision
        or resolved.audited_parent_commit != plan.audited_parent_commit
        or resolved.release_prefix != plan.release_prefix
        or resolved.release_manifest_digest != package.manifest_digest
        or resolved.sha256 != sha256(card_bytes).hexdigest()
        or resolved.size_bytes != len(card_bytes)
        or [dict(item) for item in resolved.configs] != expected_configs
    ):
        raise StateLawsPublicationPackageError(
            "Viewer-control plan differs from the exact package, plan, or card"
        )
    state_operation = {
        "unobserved": VIEWER_CONTROL_OBSERVE,
        "absent": VIEWER_CONTROL_ADD,
    }
    if resolved.existing_state in state_operation:
        if (
            resolved.operation != state_operation[resolved.existing_state]
            or resolved.expected_existing_sha256
        ):
            raise StateLawsPublicationPackageError(
                "Viewer-control remote-state operation is incoherent"
            )
    elif resolved.operation == VIEWER_CONTROL_SKIP:
        if resolved.expected_existing_sha256 != resolved.sha256:
            raise StateLawsPublicationPackageError(
                "Viewer-control skip requires an exact root-card digest match"
            )
    elif resolved.operation == VIEWER_CONTROL_REPLACE:
        if (
            not resolved.expected_existing_sha256
            or resolved.expected_existing_sha256 == resolved.sha256
        ):
            raise StateLawsPublicationPackageError(
                "Viewer-control replacement requires distinct old and new digests"
            )
        authorization = StateLawsViewerControlAuthorization.from_mapping(
            resolved.replacement_review or {}
        )
        expected = {
            "audited_parent_commit": resolved.audited_parent_commit,
            "expected_existing_sha256": resolved.expected_existing_sha256,
            "release_manifest_digest": resolved.release_manifest_digest,
            "remote_path": resolved.remote_path,
            "replacement_sha256": resolved.sha256,
            "repository_id": resolved.repository_id,
            "target_revision": resolved.target_revision,
        }
        if any(
            authorization.to_dict().get(key) != value
            for key, value in expected.items()
        ):
            raise StateLawsPublicationPackageError(
                "Viewer-control replacement authorization binding drifted"
            )
    else:
        raise StateLawsPublicationPackageError(
            "present Viewer-control state has an invalid operation"
        )
    return resolved


def _attach_state_laws_viewer_control(
    package: StateLawsPublicationPackage,
    plan: PublicationPlan,
    *,
    root_readme_exists: bool | None,
    existing_root_readme_sha256: str | None,
    replacement_authorization: (
        StateLawsViewerControlAuthorization | Mapping[str, Any] | None
    ),
) -> PublicationPlan:
    control = plan_state_laws_viewer_control(
        package,
        plan,
        root_readme_exists=root_readme_exists,
        existing_root_readme_sha256=existing_root_readme_sha256,
        replacement_authorization=replacement_authorization,
    )
    metadata = dict(plan.metadata)
    metadata["viewer_control"] = control.to_dict()
    enriched = replace(plan, metadata=metadata, plan_digest="")
    verify_state_laws_viewer_control_plan(package, enriched)
    return enriched


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
        assert_historical_baseline_pin_preserved(PREVIOUS_PUBLIC_PIN)
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
        viewer_control = verify_state_laws_viewer_control_plan(
            self.package,
            self.plan,
        )
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
            "viewer_control": viewer_control.to_dict(),
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
    root_readme_exists: bool | None = None,
    existing_root_readme_sha256: str | None = None,
    root_readme_replacement_authorization: (
        StateLawsViewerControlAuthorization | Mapping[str, Any] | None
    ) = None,
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
    root_digest = str(existing_root_readme_sha256 or "")
    remote_digests = dict(existing_remote_digests or {})
    if VIEWER_ROOT_PATH in remote_digests:
        observed = str(remote_digests[VIEWER_ROOT_PATH])
        if root_digest and root_digest != observed:
            raise StateLawsPublicationPackageError(
                "root README digest evidence disagrees"
            )
        root_digest = observed
    if VIEWER_ROOT_PATH in set(existing_remote_paths):
        if root_readme_exists is False:
            raise StateLawsPublicationPackageError(
                "root README presence evidence disagrees"
            )
        root_readme_exists = True
    plan = _attach_state_laws_viewer_control(
        package,
        plan,
        root_readme_exists=root_readme_exists,
        existing_root_readme_sha256=root_digest or None,
        replacement_authorization=root_readme_replacement_authorization,
    )
    if (
        plan.release_id != package.release_id
        or plan.release_sha256 != package.manifest_digest
        or plan.repository_id != DEFAULT_DATASET_REPO_ID
    ):
        raise StateLawsPublicationPackageError(
            "shared publisher plan drifted from the verified State Laws package"
        )
    _verify_state_laws_plan_binding(package, plan, profile)
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


def plan_state_laws_staging_publication_dry_run(
    output_root: str | Path,
    *,
    staging_branch: str,
    api: Any | None = None,
    existing_remote_paths: Sequence[str] = (),
    existing_remote_digests: Mapping[str, str] | None = None,
    audited_parent_commit: str,
    root_readme_exists: bool | None = None,
    existing_root_readme_sha256: str | None = None,
) -> StateLawsPublicationDryRun:
    """Return the exact offline plan for a dedicated State staging branch."""

    package = prepare_state_laws_publication_package(output_root)
    profile = state_laws_staging_publication_profile(staging_branch)
    publisher = HuggingFaceReleasePublisher(profile=profile, api=api)
    plan = publisher.plan_dry_run(
        package.to_publisher_manifest(),
        local_root=package.output_root,
        existing_remote_paths=existing_remote_paths,
        existing_remote_digests=existing_remote_digests,
        audited_parent_commit=audited_parent_commit,
        target_revision=staging_branch,
    )
    root_digest = str(existing_root_readme_sha256 or "")
    remote_digests = dict(existing_remote_digests or {})
    if VIEWER_ROOT_PATH in remote_digests:
        observed = str(remote_digests[VIEWER_ROOT_PATH])
        if root_digest and root_digest != observed:
            raise StateLawsPublicationPackageError(
                "staging root README digest evidence disagrees"
            )
        root_digest = observed
    if VIEWER_ROOT_PATH in set(existing_remote_paths):
        if root_readme_exists is False:
            raise StateLawsPublicationPackageError(
                "staging root README presence evidence disagrees"
            )
        root_readme_exists = True
    plan = _attach_state_laws_viewer_control(
        package,
        plan,
        root_readme_exists=root_readme_exists,
        existing_root_readme_sha256=root_digest or None,
        replacement_authorization=None,
    )
    _verify_state_laws_plan_binding(
        package,
        plan,
        profile,
        target_revision=staging_branch,
    )
    receipt = publisher.build_publication_receipt(
        plan=plan,
        status="dry_run_only",
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
    *,
    target_revision: str = "main",
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
        or plan.target_revision != target_revision
        or plan.release_id != package.release_id
        or plan.release_sha256 != package.manifest_digest
        or plan.release_prefix != official.release_prefix_for(package.release_id)
    ):
        raise StateLawsPublicationPackageError(
            "publisher plan is not bound to the official State Laws release"
        )
    verify_state_laws_viewer_control_plan(package, plan)

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
        or normalized.previous_public_pin != PUBLICATION_PARENT_REVISION
        or normalized.previous_public_pin != plan.audited_parent_commit
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
            or normalized.previous_public_pin != PUBLICATION_PARENT_REVISION
            or normalized.previous_public_pin != plan.audited_parent_commit
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
    staging_candidate_digest: str
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
            "staging_candidate_digest": self.staging_candidate_digest,
            "staging_revision": self.staging_revision,
        }


@dataclass(frozen=True, slots=True)
class StateLawsStagingControlBundle:
    """Local-only canonical card/proof binding prepared before staging."""

    candidate_manifest_digest: str
    candidate_path: str
    dataset_card_path: str
    dataset_card_sha256: str
    plan_digest: str
    policy_proof_digest: str
    release_manifest_digest: str
    source_rights_receipt_digest: str
    staging_branch: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_manifest_digest": self.candidate_manifest_digest,
            "candidate_path": self.candidate_path,
            "dataset_card_path": self.dataset_card_path,
            "dataset_card_sha256": self.dataset_card_sha256,
            "hub_mutation_performed": False,
            "network_io_performed": False,
            "plan_digest": self.plan_digest,
            "policy_proof_digest": self.policy_proof_digest,
            "release_manifest_digest": self.release_manifest_digest,
            "source_rights_receipt_digest": self.source_rights_receipt_digest,
            "staging_branch": self.staging_branch,
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


def _load_canonical_control_json(
    repository_root: Path,
    relative_path: str,
    *,
    label: str,
    maximum_bytes: int = 64 * 1024 * 1024,
) -> tuple[dict[str, Any], bytes]:
    encoded = _read_regular_file_nofollow(
        repository_root / relative_path,
        label=label,
        maximum_bytes=maximum_bytes,
    )
    try:
        payload = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except StateLawsPublicationPackageError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(f"{label} is malformed") from exc
    if type(payload) is not dict:
        raise StateLawsPublicationPackageError(f"{label} must be a JSON object")
    return payload, encoded


def _validate_state_laws_staging_receipt(
    payload: Mapping[str, Any],
    *,
    label: str,
    staging_candidate_digest: str,
    release_manifest_digest: str,
    dataset_repo_id: str,
    staging_revision: str | None = None,
) -> None:
    if (
        payload.get("status") != "passed"
        or payload.get("fixture_only") is not False
        or payload.get("dirty") is not False
        or payload.get("dataset_repo_id") != dataset_repo_id
    ):
        raise StateLawsPublicationPackageError(
            f"{label} is not clean passed production evidence"
        )
    bound_candidate = _require_sha256(
        payload.get("final_manifest_digest"),
        label=f"{label} final_manifest_digest",
    )
    bound_release = _require_sha256(
        payload.get("release_manifest_digest"),
        label=f"{label} release_manifest_digest",
    )
    if bound_candidate != staging_candidate_digest:
        raise StateLawsPublicationPackageError(
            f"{label} does not bind the null publication candidate A"
        )
    if bound_release != release_manifest_digest:
        raise StateLawsPublicationPackageError(
            f"{label} release manifest differs from the publication plan"
        )
    if staging_revision is not None:
        observed_revision = str(payload.get("staging_revision") or "")
        if observed_revision != staging_revision:
            raise StateLawsPublicationPackageError(
                f"{label} staging revision differs from the policy proof"
            )


def _lcr084_candidate_report_digest(payload: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key != "report_digest_sha256"
    }
    return sha256(canonical_json_bytes(body)).hexdigest()


def _lcr084_staging_candidate_digest(payload: Mapping[str, Any]) -> str:
    staging = dict(payload)
    staging["publication_binding"] = None
    return _lcr084_candidate_report_digest(staging)


def _check_lcr084_candidate_in_subprocess(
    candidate_bytes: bytes,
    *,
    repository_root: Path,
    phase: str,
) -> dict[str, Any]:
    """Run the exact @2 builder checker in a private isolated import graph."""

    if phase not in {"state_staging", "state_main"}:
        raise StateLawsPublicationPackageError(
            f"unsupported LCR-084 candidate phase: {phase!r}"
        )
    if len(candidate_bytes) > 64 * 1024 * 1024:
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 candidate exceeds its validation byte bound"
        )
    implementation_root = Path(__file__).resolve().parents[3]
    builder_filename = "_".join(("build", "state", "laws", "hf", "release")) + ".py"
    source_path = implementation_root / "scripts/ops/legal_data" / builder_filename
    source_bytes = _read_regular_file_nofollow(
        source_path,
        label="canonical LCR-084 candidate builder",
        maximum_bytes=16 * 1024 * 1024,
    )
    child_source = (
        "import importlib.util,json,os,pathlib,resource,sys,types\n"
        "resource.setrlimit(resource.RLIMIT_FSIZE,(65536,65536))\n"
        "source_fd=int(sys.argv[1])\n"
        "source=pathlib.Path(sys.argv[2]).resolve()\n"
        "implementation_root=pathlib.Path(sys.argv[3]).resolve()\n"
        "evidence_root=pathlib.Path(sys.argv[4]).resolve()\n"
        "phase=sys.argv[5]\n"
        "sys.path.insert(0,str(implementation_root))\n"
        "with os.fdopen(os.dup(source_fd),'rb') as stream:\n"
        " source_bytes=stream.read(16777217)\n"
        "assert len(source_bytes)<=16777216\n"
        "name='_lcr084_package_builder'\n"
        "spec=importlib.util.spec_from_loader(name,loader=None,origin=str(source))\n"
        "module=types.ModuleType(name)\n"
        "module.__file__=str(source)\n"
        "module.__package__=''\n"
        "module.__spec__=spec\n"
        "sys.modules[name]=module\n"
        "exec(compile(source_bytes,str(source),'exec'),module.__dict__)\n"
        "raw=sys.stdin.buffer.read(67108865)\n"
        "assert len(raw)<=67108864\n"
        "payload=module.load_json_value_bytes(raw,label='canonical LCR-084 candidate')\n"
        "checked=module.check_production_candidate_report(payload,repo_root=evidence_root,remeasure_production_evidence=False)\n"
        "module.check_production_candidate_publication_binding(payload,phase=phase)\n"
        "result={'checked':checked,'phase':phase,'report_digest_sha256':module._digest_for_report(payload),'staging_candidate_digest':module.production_candidate_staging_digest(payload)}\n"
        "sys.stdout.write(json.dumps(result,sort_keys=True,separators=(',',':')))\n"
    )
    with (
        tempfile.TemporaryFile() as source_snapshot,
        tempfile.TemporaryFile() as candidate_snapshot,
        tempfile.TemporaryFile() as stdout_snapshot,
        tempfile.TemporaryFile() as stderr_snapshot,
    ):
        source_snapshot.write(source_bytes)
        source_snapshot.seek(0)
        candidate_snapshot.write(candidate_bytes)
        candidate_snapshot.seek(0)
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    child_source,
                    str(source_snapshot.fileno()),
                    str(source_path),
                    str(implementation_root),
                    str(repository_root),
                    phase,
                ],
                cwd=implementation_root,
                env={
                    "PATH": os.environ.get("PATH", os.defpath),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONHASHSEED": "0",
                },
                pass_fds=(source_snapshot.fileno(),),
                stdin=candidate_snapshot,
                stdout=stdout_snapshot,
                stderr=stderr_snapshot,
                start_new_session=True,
            )
        except OSError as exc:
            raise StateLawsPublicationPackageError(
                "canonical LCR-084 candidate checker could not start"
            ) from exc
        try:
            process.communicate(timeout=180)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            process.communicate()
            raise StateLawsPublicationPackageError(
                "canonical LCR-084 candidate checker timed out"
            ) from exc
        stdout_snapshot.seek(0)
        stdout = stdout_snapshot.read(64 * 1024 + 1)
        stderr_snapshot.seek(0)
        stderr = stderr_snapshot.read(64 * 1024 + 1)
    if (
        _read_regular_file_nofollow(
            source_path,
            label="canonical LCR-084 candidate builder bookend",
            maximum_bytes=16 * 1024 * 1024,
        )
        != source_bytes
    ):
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 candidate builder changed during validation"
        )
    if len(stdout) > 64 * 1024 or len(stderr) > 64 * 1024:
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 candidate checker exceeded its output bound"
        )
    if process.returncode != 0:
        diagnostic = stderr.decode("utf-8", errors="replace")[-2048:]
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 candidate failed strict validation: "
            + diagnostic
        )
    try:
        result = json.loads(
            stdout.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 candidate checker returned malformed JSON"
        ) from exc
    expected_checked = {
        "jurisdiction_count": 51,
        "ok": True,
        "task_id": "LCR-084",
        "valid": True,
    }
    if (
        type(result) is not dict
        or set(result)
        != {
            "checked",
            "phase",
            "report_digest_sha256",
            "staging_candidate_digest",
        }
        or result.get("checked") != expected_checked
        or result.get("phase") != phase
    ):
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 candidate checker returned an unexpected result"
        )
    _require_sha256(
        result.get("report_digest_sha256"),
        label="checked LCR-084 report digest",
    )
    _require_sha256(
        result.get("staging_candidate_digest"),
        label="checked LCR-084 staging digest",
    )
    return result


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


def materialize_state_laws_staging_controls(
    package: StateLawsPublicationPackage,
    plan: PublicationPlan,
    *,
    repository_root: str | Path,
) -> StateLawsStagingControlBundle:
    """Write the canonical State card and bind an exact staging plan locally."""

    from ipfs_datasets_py.huggingface.publisher import (
        canonical_legal_corpora_policy_proof_digest,
    )
    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as canonical_runtime,
    )
    from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
        LIVE_COMPLIANCE_REPORT_SCHEMA,
    )

    canonical_root = Path(repository_root).expanduser()
    verify_state_laws_publication_package_identity(package)
    profile = state_laws_staging_publication_profile(plan.target_revision)
    _verify_state_laws_plan_binding(
        package,
        plan,
        profile,
        target_revision=plan.target_revision,
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
    if (
        manifest.get("fixture_only") is True
        or str(manifest.get("mode") or "").casefold()
        in {"fixture", "fixture_only", "test"}
        or "fixture" in str(manifest.get("release_point") or "").casefold()
    ):
        raise StateLawsPublicationPackageError(
            "fixture State Laws releases cannot produce staging controls"
        )
    validate_exact_51_coverage(manifest.get("jurisdictions") or ())

    package_rights_bytes = _read_regular_file_nofollow(
        Path(package.output_root) / SOURCE_RIGHTS_RECEIPT_RELPATH,
        label="packaged State Laws source-rights receipt",
        maximum_bytes=16 * 1024 * 1024,
    )
    canonical_rights_bytes = _read_regular_file_nofollow(
        canonical_root / SOURCE_RIGHTS_RECEIPT_RELPATH,
        label="canonical State Laws source-rights receipt",
        maximum_bytes=16 * 1024 * 1024,
    )
    if package_rights_bytes != canonical_rights_bytes:
        raise StateLawsPublicationPackageError(
            "packaged and canonical source-rights receipt bytes differ"
        )
    try:
        rights = json.loads(
            canonical_rights_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawsPublicationPackageError(
            "canonical source-rights receipt is malformed"
        ) from exc
    require_live_source_rights_receipt(rights)
    if (
        rights.get("report_schema") != LIVE_COMPLIANCE_REPORT_SCHEMA
        or rights.get("status") != "passed"
        or rights.get("authorizing_for_publication") is not True
        or rights.get("fixture_only_non_authorizing") is not False
    ):
        raise StateLawsPublicationPackageError(
            "canonical source-rights receipt is non-authorizing"
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

    candidate, candidate_bytes = _load_canonical_control_json(
        canonical_root,
        canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH,
        label="canonical LCR-084 staging candidate",
    )
    if candidate.get("schema") != canonical_runtime.PRODUCTION_MANIFEST_SCHEMA_V2:
        raise StateLawsPublicationPackageError(
            "State staging controls require the canonical LCR-084 @2 candidate"
        )
    check = _check_lcr084_candidate_in_subprocess(
        candidate_bytes,
        repository_root=canonical_root,
        phase="state_staging",
    )
    candidate_digest = str(check["staging_candidate_digest"])
    if (
        candidate.get("publication_binding") is not None
        or candidate.get("report_digest_sha256") != candidate_digest
        or candidate.get("dataset_repo_id") != plan.repository_id
        or candidate.get("manifest_digest") != plan.release_sha256
        or candidate.get("source_rights_receipt_digest") != rights_digest
    ):
        raise StateLawsPublicationPackageError(
            "canonical staging candidate differs from the package, plan, or rights receipt"
        )
    proof_digest = canonical_legal_corpora_policy_proof_digest(
        phase="state_staging",
        candidate_manifest_digest=candidate_digest,
        plan=plan,
    )
    viewer_control = verify_state_laws_viewer_control_plan(package, plan)
    card_bytes = state_laws_viewer_control_card_bytes(
        package,
        release_prefix=plan.release_prefix,
    )
    if sha256(card_bytes).hexdigest() != viewer_control.sha256:
        raise StateLawsPublicationPackageError(
            "staging Viewer control bytes differ from the reviewed plan"
        )
    if (
        _read_regular_file_nofollow(
            canonical_root / canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH,
            label="canonical staging candidate bookend",
            maximum_bytes=64 * 1024 * 1024,
        )
        != candidate_bytes
        or _read_regular_file_nofollow(
            canonical_root / SOURCE_RIGHTS_RECEIPT_RELPATH,
            label="canonical source-rights receipt bookend",
            maximum_bytes=16 * 1024 * 1024,
        )
        != canonical_rights_bytes
    ):
        raise StateLawsPublicationPackageError(
            "canonical State Laws controls changed during materialization"
        )
    _atomic_write_canonical_controls(
        canonical_root,
        {canonical_runtime.STATE_DATASET_CARD_RELPATH: card_bytes},
    )
    return StateLawsStagingControlBundle(
        candidate_manifest_digest=candidate_digest,
        candidate_path=canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH,
        dataset_card_path=canonical_runtime.STATE_DATASET_CARD_RELPATH,
        dataset_card_sha256=sha256(card_bytes).hexdigest(),
        plan_digest=plan.plan_digest,
        policy_proof_digest=proof_digest,
        release_manifest_digest=plan.release_sha256,
        source_rights_receipt_digest=rights_digest,
        staging_branch=plan.target_revision,
    )


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
    canonical_root = Path(repository_root).expanduser()
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
    repository_rights_path = canonical_root / SOURCE_RIGHTS_RECEIPT_RELPATH
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
    staging_revision = canonical_runtime.require_immutable_revision(
        str(request.get("staging_revision") or ""),
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

    staging_candidate, staging_candidate_bytes = _load_canonical_control_json(
        canonical_root,
        canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH,
        label="canonical LCR-084 staging candidate",
    )
    if (
        staging_candidate.get("schema")
        != canonical_runtime.PRODUCTION_MANIFEST_SCHEMA_V2
    ):
        raise StateLawsPublicationPackageError(
            "State Laws main controls require the canonical LCR-084 @2 candidate; "
            "the generic @1 manifest cannot authorize main publication"
        )
    existing_publication_binding = staging_candidate.get(
        "publication_binding"
    )
    if existing_publication_binding is None:
        candidate_phase = "state_staging"
    elif type(existing_publication_binding) is dict:
        candidate_phase = "state_main"
        if existing_publication_binding != {
            "plan_digest": plan.plan_digest,
            "policy_proof_digest": sealed.proof_digest,
            "release_manifest_digest": plan.release_sha256,
            "staging_candidate_digest": existing_publication_binding.get(
                "staging_candidate_digest"
            ),
        }:
            raise StateLawsPublicationPackageError(
                "existing State Laws main candidate differs from the exact "
                "plan or sealed policy proof"
            )
    else:
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 publication binding is malformed"
        )
    staging_check = _check_lcr084_candidate_in_subprocess(
        staging_candidate_bytes,
        repository_root=canonical_root,
        phase=candidate_phase,
    )
    staging_candidate_digest = str(
        staging_check["staging_candidate_digest"]
    )
    if (
        staging_candidate.get("report_digest_sha256")
        != staging_check["report_digest_sha256"]
        or staging_candidate.get("dataset_repo_id") != plan.repository_id
        or staging_candidate.get("manifest_digest") != plan.release_sha256
        or staging_candidate.get("source_rights_catalog_digest") != catalog_digest
        or staging_candidate.get("source_rights_receipt_digest") != rights_digest
    ):
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 staging candidate differs from the exact package, "
            "plan, or source-rights receipt"
        )

    staging_receipt_snapshots: dict[str, bytes] = {}
    for relative_path, label, expected_revision in (
        (
            STATE_LAWS_STAGING_UPLOAD_RELPATH,
            "State Laws staging upload receipt",
            None,
        ),
        (
            STATE_LAWS_STAGING_CANARY_RELPATH,
            "State Laws staging canary receipt",
            staging_revision,
        ),
    ):
        receipt, receipt_bytes = _load_canonical_control_json(
            canonical_root,
            relative_path,
            label=label,
            maximum_bytes=16 * 1024 * 1024,
        )
        if receipt.get("schema") != canonical_runtime.RECEIPT_SCHEMA_V1:
            raise StateLawsPublicationPackageError(
                f"{label} is not a canonical generic receipt"
            )
        try:
            canonical_runtime.verify_independent_digests(
                relpath=relative_path,
                raw=receipt_bytes,
                payload=receipt,
            )
            canonical_runtime.load_receipt(canonical_root, relative_path)
        except Exception as exc:
            raise StateLawsPublicationPackageError(
                f"{label} failed canonical receipt validation: {exc}"
            ) from exc
        _validate_state_laws_staging_receipt(
            receipt,
            label=label,
            staging_candidate_digest=staging_candidate_digest,
            release_manifest_digest=plan.release_sha256,
            dataset_repo_id=plan.repository_id,
            staging_revision=expected_revision,
        )
        if (
            _read_regular_file_nofollow(
                canonical_root / relative_path,
                label=f"{label} bookend",
                maximum_bytes=16 * 1024 * 1024,
            )
            != receipt_bytes
        ):
            raise StateLawsPublicationPackageError(
                f"{label} changed during validation"
            )
        staging_receipt_snapshots[relative_path] = receipt_bytes

    candidate = _canonical_mapping(
        staging_candidate,
        label="canonical LCR-084 main candidate",
    )
    candidate["publication_binding"] = {
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": sealed.proof_digest,
        "release_manifest_digest": plan.release_sha256,
        "staging_candidate_digest": staging_candidate_digest,
    }
    candidate["report_digest_sha256"] = _lcr084_candidate_report_digest(candidate)
    candidate_digest = str(candidate["report_digest_sha256"])
    if candidate_digest == staging_candidate_digest:
        raise StateLawsPublicationPackageError(
            "main candidate digest B must differ from staging candidate digest A"
        )
    if set(candidate) != set(staging_candidate) or any(
        candidate[key] != staging_candidate[key]
        for key in candidate
        if key not in {"publication_binding", "report_digest_sha256"}
    ):
        raise StateLawsPublicationPackageError(
            "main candidate promotion changed fields outside publication_binding"
        )
    main_check = _check_lcr084_candidate_in_subprocess(
        canonical_json_bytes(candidate),
        repository_root=canonical_root,
        phase="state_main",
    )
    if (
        main_check["report_digest_sha256"] != candidate_digest
        or main_check["staging_candidate_digest"]
        != staging_candidate_digest
    ):
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 main candidate digest chain failed validation"
        )
    candidate_bytes = canonical_json_bytes(candidate) + b"\n"
    viewer_control = verify_state_laws_viewer_control_plan(package, plan)
    card_bytes = state_laws_viewer_control_card_bytes(
        package,
        release_prefix=plan.release_prefix,
    )
    if sha256(card_bytes).hexdigest() != viewer_control.sha256:
        raise StateLawsPublicationPackageError(
            "main Viewer control bytes differ from the reviewed plan"
        )
    seal_payload = {
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "created_after_mutation": False,
        "dataset_repo_id": plan.repository_id,
        "dirty": False,
        "final_manifest_digest": candidate_digest,
        "fixture_only": False,
        "goal_id": "LCR-G080",
        "live_staging": True,
        "manifest_digest": candidate_digest,
        "mutation_executed": False,
        "network_mutation": False,
        "no_mutation": True,
        "no_mutate": True,
        "operation": "additive_main_upload",
        "phase": "state_main",
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": sealed.proof_digest,
        "post_hoc": False,
        "present": True,
        "previous_public_pin": plan.audited_parent_commit,
        "producer": "seal_state_laws_prepublication.py",
        "program_id": "legal-corpora-reindex-v1",
        "release_manifest_digest": plan.release_sha256,
        "schema": canonical_runtime.SEAL_SCHEMA_V1,
        "sealed_at": sealed_at,
        "staging_revision": staging_revision,
        "status": "sealed",
        "target_repo": plan.repository_id,
        "task_id": "LCR-072",
        "timing": "before_mutation",
    }
    _, seal_digest, seal_bytes = _canonical_control_receipt(seal_payload)
    files = {
        canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH: candidate_bytes,
        canonical_runtime.STATE_DATASET_CARD_RELPATH: card_bytes,
        canonical_runtime.STATE_PREPUBLICATION_SEAL_RELPATH: seal_bytes,
    }
    if (
        _read_regular_file_nofollow(
            canonical_root
            / canonical_runtime.STATE_CANDIDATE_MANIFEST_RELPATH,
            label="canonical LCR-084 staging candidate bookend",
            maximum_bytes=64 * 1024 * 1024,
        )
        != staging_candidate_bytes
    ):
        raise StateLawsPublicationPackageError(
            "canonical LCR-084 staging candidate changed during promotion"
        )
    for relative_path, expected_bytes in staging_receipt_snapshots.items():
        if (
            _read_regular_file_nofollow(
                canonical_root / relative_path,
                label=f"{relative_path} final bookend",
                maximum_bytes=16 * 1024 * 1024,
            )
            != expected_bytes
        ):
            raise StateLawsPublicationPackageError(
                f"{relative_path} changed during candidate promotion"
            )
    _atomic_write_canonical_controls(canonical_root, files)
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
        staging_candidate_digest=staging_candidate_digest,
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
    "VIEWER_CONTROL_ADD",
    "VIEWER_CONTROL_AUTHORIZATION_SCHEMA_VERSION",
    "VIEWER_CONTROL_OBSERVE",
    "VIEWER_CONTROL_REPLACE",
    "VIEWER_CONTROL_SCHEMA_VERSION",
    "VIEWER_CONTROL_SKIP",
    "VIEWER_ROOT_PATH",
    "StateLawsCanonicalControlBundle",
    "StateLawsStagingControlBundle",
    "StateLawsPublicationDryRun",
    "StateLawsLivePolicyProof",
    "StateLawsPublicationPackage",
    "StateLawsPublicationPackageError",
    "StateLawsViewerControlAuthorization",
    "StateLawsViewerControlPlan",
    "materialize_state_laws_canonical_controls",
    "materialize_state_laws_staging_controls",
    "plan_state_laws_publication_dry_run",
    "plan_state_laws_staging_publication_dry_run",
    "plan_state_laws_viewer_control",
    "prepare_state_laws_publication_package",
    "require_state_laws_policy_binding",
    "state_laws_publication_profile",
    "state_laws_staging_publication_profile",
    "state_laws_viewer_control_card_bytes",
    "verify_state_laws_live_policy_proof",
    "verify_state_laws_publication_package_identity",
    "verify_state_laws_viewer_control_plan",
]
