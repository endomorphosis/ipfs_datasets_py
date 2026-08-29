"""Artifact-preserving Federal Register publication package and controls.

The module performs local packaging and canonical-control materialization only.
Every protected Hub mutation remains owned by the shared publisher/runtime.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.huggingface.publication_profile import (
    BASE_PROHIBITED_OPERATIONS,
    HuggingFacePublicationProfile,
)
from ipfs_datasets_py.huggingface.publisher import (
    HuggingFaceReleasePublisher,
    PublicationPlan,
    canonical_json_bytes,
    canonical_legal_corpora_policy_proof_digest,
)
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (
    MANIFEST_FILENAME,
    FederalRegisterHuggingFaceRelease,
    validate_federal_register_hf_release,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN,
)
from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    LIVE_COMPLIANCE_REPORT_SCHEMA,
    require_live_source_rights_receipt,
)

SCHEMA_VERSION: Final = "federal-register-publication-package/v1"
PROFILE_ID: Final = "federal-register"
PROGRAM_ID: Final = "federal-register-sparse-graphrag"
GOAL_ID: Final = "LCR-G130"
PLAN_SCHEMA: Final = "federal-register-hf-publication-plan/v1"
RECEIPT_SCHEMA: Final = "federal-register-hf-publication-receipt/v1"
RELEASE_PREFIX_TEMPLATE: Final = "data/federal_register/{release_id}"
POINTER_PATH: Final = "runtime/federal_register_release_pointer.json"
COMMIT_MESSAGE: Final = (
    "federal-register: append-only immutable sparse GraphRAG release"
)
DEFAULT_STAGING_BRANCH: Final = "stage/federal-register-ir-graphrag-v2"
STAGING_CANARY_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_staging_canary.json"
)
SOURCE_RIGHTS_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json"
)


class FederalRegisterPublicationPackageError(ValueError):
    """Raised when Federal publication inputs are not exactly bound."""


def _digest(value: Any, *, label: str) -> str:
    text = str(value or "").strip().casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise FederalRegisterPublicationPackageError(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return text


def _git_sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().casefold()
    if len(text) != 40 or any(character not in "0123456789abcdef" for character in text):
        raise FederalRegisterPublicationPackageError(
            f"{label} must be an exact 40-hex Git SHA"
        )
    return text


def _safe_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise FederalRegisterPublicationPackageError(
            f"unsafe Federal release path: {value!r}"
        )
    return path.as_posix()


def _candidate_digest(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_digest"}
    return sha256(canonical_json_bytes(body)).hexdigest()


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise FederalRegisterPublicationPackageError(
            f"{label} is missing or unsafe"
        )
    encoded = path.read_bytes()
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FederalRegisterPublicationPackageError(f"{label} is malformed") from exc
    if type(payload) is not dict:
        raise FederalRegisterPublicationPackageError(f"{label} must be an object")
    return payload, encoded


def federal_register_publication_profile() -> HuggingFacePublicationProfile:
    return HuggingFacePublicationProfile(
        profile_id=PROFILE_ID,
        program_id=PROGRAM_ID,
        goal_id=GOAL_ID,
        plan_schema_version=PLAN_SCHEMA,
        receipt_schema_version=RECEIPT_SCHEMA,
        canonical_release_schema="federal-register-hf-release/v1",
        repository_id=DEFAULT_DATASET_REPO_ID,
        repository_type="dataset",
        release_prefix_template=RELEASE_PREFIX_TEMPLATE,
        pointer_path=POINTER_PATH,
        target_revision="main",
        commit_message=COMMIT_MESSAGE,
        prohibited_operations=BASE_PROHIBITED_OPERATIONS,
        require_pinned_verification_before_promotion=True,
        allow_remote_write_on_dry_run=False,
        metadata={"artifact_preserving": True, "program": PROGRAM_ID},
    )


@dataclass(frozen=True, slots=True)
class FederalRegisterPublicationPackage:
    output_root: str
    manifest_digest: str
    manifest_file_sha256: str
    release_id: str
    source_rights_receipt_digest: str
    descriptors: tuple[Mapping[str, Any], ...]
    dataset_card_text: str

    def to_publisher_manifest(self) -> dict[str, Any]:
        return {
            "artifact_preserving": True,
            "descriptors": [dict(item) for item in self.descriptors],
            "manifest_file_sha256": self.manifest_file_sha256,
            "release_id": self.release_id,
            "release_sha256": self.manifest_digest,
            "schema_version": SCHEMA_VERSION,
        }


@dataclass(frozen=True, slots=True)
class FederalRegisterCanonicalControlBundle:
    phase: str
    candidate_manifest_digest: str
    staging_candidate_digest: str
    candidate_path: str
    dataset_card_path: str
    dataset_card_sha256: str
    release_manifest_digest: str
    plan_digest: str
    policy_proof_digest: str
    source_rights_receipt_digest: str
    staging_revision: str
    seal_path: str = ""
    seal_content_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_manifest_digest": self.candidate_manifest_digest,
            "candidate_path": self.candidate_path,
            "dataset_card_path": self.dataset_card_path,
            "dataset_card_sha256": self.dataset_card_sha256,
            "hub_mutation_performed": False,
            "network_io_performed": False,
            "phase": self.phase,
            "plan_digest": self.plan_digest,
            "policy_proof_digest": self.policy_proof_digest,
            "release_manifest_digest": self.release_manifest_digest,
            "seal_content_digest": self.seal_content_digest,
            "seal_path": self.seal_path,
            "source_rights_receipt_digest": self.source_rights_receipt_digest,
            "staging_candidate_digest": self.staging_candidate_digest,
            "staging_revision": self.staging_revision,
        }


def materialize_federal_register_release_tree(
    release: FederalRegisterHuggingFaceRelease,
    output_root: str | Path,
) -> Path:
    """Materialize exact release bytes additively and refuse every conflict."""

    if type(release) is not FederalRegisterHuggingFaceRelease:
        raise FederalRegisterPublicationPackageError(
            "release must be an exact FederalRegisterHuggingFaceRelease"
        )
    validate_federal_register_hf_release(release)
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for artifact in release.artifacts:
        relative = _safe_path(artifact.relative_path)
        target = root.joinpath(*PurePosixPath(relative).parts)
        if target.is_symlink():
            raise FederalRegisterPublicationPackageError(
                f"release target is a symlink: {relative}"
            )
        if target.exists():
            if not target.is_file() or target.read_bytes() != artifact.content:
                raise FederalRegisterPublicationPackageError(
                    f"additive release target conflicts with reviewed bytes: {relative}"
                )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.partial-{os.getpid()}")
        temporary.write_bytes(artifact.content)
        os.replace(temporary, target)
    return root


def prepare_federal_register_publication_package(
    release: FederalRegisterHuggingFaceRelease,
    *,
    output_root: str | Path,
) -> FederalRegisterPublicationPackage:
    """Verify and package exact Federal release bytes for the shared publisher."""

    root = materialize_federal_register_release_tree(release, output_root)
    manifest = release.manifest_dict()
    manifest_digest = _digest(release.manifest_digest, label="manifest_digest")
    if (
        manifest.get("manifest_digest") != manifest_digest
        or manifest.get("dataset_repo_id") != DEFAULT_DATASET_REPO_ID
        or manifest.get("additive_packaging") is not True
        or manifest.get("legacy_files_deleted") is not False
        or manifest.get("authorizing_for_publication") is not False
        or manifest.get("rollback", {}).get("previous_public_pin")
        != PREVIOUS_PUBLIC_PIN
    ):
        raise FederalRegisterPublicationPackageError(
            "Federal release manifest weakens the canonical publication contract"
        )
    descriptors: list[Mapping[str, Any]] = []
    for artifact in release.artifacts:
        relative = _safe_path(artifact.relative_path)
        body = (root / relative).read_bytes()
        if (
            len(body) != artifact.size_bytes
            or sha256(body).hexdigest() != artifact.sha256
        ):
            raise FederalRegisterPublicationPackageError(
                f"Federal release artifact drifted: {relative}"
            )
        descriptors.append(
            MappingProxyType(
                {
                    "content_cid": artifact.content_cid,
                    "family": artifact.family,
                    "media_type": artifact.media_type,
                    "operation": "add_only_upload",
                    "relative_path": relative,
                    "row_count": artifact.row_count,
                    "schema_id": artifact.schema_id,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                }
            )
        )
    descriptors.sort(key=lambda item: str(item["relative_path"]))
    manifest_bytes = (root / MANIFEST_FILENAME).read_bytes()
    rights_digest = _digest(
        release.source_rights_receipt_digest,
        label="source_rights_receipt_digest",
    )
    card = release.dataset_card_text()
    if rights_digest not in card and rights_digest[:16] not in card:
        raise FederalRegisterPublicationPackageError(
            "Federal dataset card does not bind the source-rights receipt"
        )
    return FederalRegisterPublicationPackage(
        output_root=str(root),
        manifest_digest=manifest_digest,
        manifest_file_sha256=sha256(manifest_bytes).hexdigest(),
        release_id=f"sha256-{manifest_digest}",
        source_rights_receipt_digest=rights_digest,
        descriptors=tuple(descriptors),
        dataset_card_text=card,
    )


def plan_federal_register_publication_dry_run(
    package: FederalRegisterPublicationPackage,
    *,
    audited_parent_commit: str,
    target_revision: str = "main",
    api: Any | None = None,
) -> PublicationPlan:
    if type(package) is not FederalRegisterPublicationPackage:
        raise FederalRegisterPublicationPackageError(
            "package must be an exact FederalRegisterPublicationPackage"
        )
    parent = _git_sha(audited_parent_commit, label="audited_parent_commit")
    publisher = HuggingFaceReleasePublisher(
        profile=federal_register_publication_profile(),
        api=api,
    )
    plan = publisher.plan_dry_run(
        package.to_publisher_manifest(),
        local_root=package.output_root,
        audited_parent_commit=parent,
        target_revision=target_revision,
    )
    if (
        plan.repository_id != DEFAULT_DATASET_REPO_ID
        or plan.release_sha256 != package.manifest_digest
        or plan.release_id != package.release_id
    ):
        raise FederalRegisterPublicationPackageError(
            "shared publisher plan drifted from the Federal package"
        )
    return plan


def _canonical_rights(
    repository_root: Path,
    package: FederalRegisterPublicationPackage,
) -> tuple[dict[str, Any], bytes, str]:
    rights, encoded = _read_json(
        repository_root / SOURCE_RIGHTS_RELPATH,
        label="canonical source-rights receipt",
    )
    require_live_source_rights_receipt(rights)
    digest = _digest(rights.get("report_digest_sha256"), label="rights digest")
    body = dict(rights)
    body.pop("report_digest_sha256", None)
    if (
        rights.get("report_schema") != LIVE_COMPLIANCE_REPORT_SCHEMA
        or rights.get("status") != "passed"
        or rights.get("authorizing_for_publication") is not True
        or rights.get("fixture_only_non_authorizing") is not False
        or sha256(canonical_json_bytes(body)).hexdigest() != digest
        or digest != package.source_rights_receipt_digest
    ):
        raise FederalRegisterPublicationPackageError(
            "Federal canonical rights receipt is not live and package-bound"
        )
    return rights, encoded, digest


def _validate_candidate_base(
    candidate: Mapping[str, Any],
    *,
    package: FederalRegisterPublicationPackage,
    rights_digest: str,
) -> dict[str, Any]:
    payload = json.loads(canonical_json_bytes(dict(candidate)))
    declared = _digest(
        payload.get("content_digest"),
        label="Federal candidate content_digest",
    )
    if _candidate_digest(payload) != declared:
        raise FederalRegisterPublicationPackageError(
            "Federal candidate content digest does not match its body"
        )
    nested = payload.get("candidate")
    source_rights = payload.get("source_rights")
    if (
        payload.get("schema")
        != "ipfs_datasets_py/legal-corpora-reindex-federal-candidate@1"
        or payload.get("fixture_only") is not False
        or payload.get("mode") not in {"live", "production", "live_official"}
        or payload.get("authorizing_for_publication") is not False
        or payload.get("authorizing_hub_upload") is not False
        or payload.get("hub_upload") is not False
        or not isinstance(nested, Mapping)
        or nested.get("dataset_id") != DEFAULT_DATASET_REPO_ID
        or nested.get("manifest_digest") != package.manifest_digest
        or not isinstance(source_rights, Mapping)
        or source_rights.get("receipt_digest") != rights_digest
    ):
        raise FederalRegisterPublicationPackageError(
            "Federal publication candidate is fixture, unsafe, or package-unbound"
        )
    payload["publication_binding"] = None
    payload.pop("plan_digest", None)
    payload.pop("policy_proof_digest", None)
    payload["content_digest"] = _candidate_digest(payload)
    return payload


def materialize_federal_register_staging_controls(
    package: FederalRegisterPublicationPackage,
    plan: PublicationPlan,
    candidate: Mapping[str, Any],
    *,
    repository_root: str | Path,
) -> FederalRegisterCanonicalControlBundle:
    """Write the production Federal candidate/card before staging mutation."""

    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )
    from ipfs_datasets_py.processors.legal_data.state_laws_publication_package import (
        _atomic_write_canonical_controls,
    )

    root = Path(repository_root).expanduser()
    if plan.target_revision == "main":
        raise FederalRegisterPublicationPackageError(
            "Federal staging controls require a dedicated staging branch"
        )
    if (
        plan.repository_id != DEFAULT_DATASET_REPO_ID
        or plan.release_sha256 != package.manifest_digest
    ):
        raise FederalRegisterPublicationPackageError(
            "Federal staging plan differs from the exact package"
        )
    _, rights_bytes, rights_digest = _canonical_rights(root, package)
    base = _validate_candidate_base(
        candidate,
        package=package,
        rights_digest=rights_digest,
    )
    staging_digest = str(base["content_digest"])
    proof_digest = canonical_legal_corpora_policy_proof_digest(
        phase="federal_staging",
        candidate_manifest_digest=staging_digest,
        plan=plan,
    )
    bound = dict(base)
    bound["plan_digest"] = plan.plan_digest
    bound["policy_proof_digest"] = proof_digest
    bound["publication_binding"] = {
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": proof_digest,
        "release_manifest_digest": package.manifest_digest,
        "staging_candidate_digest": staging_digest,
    }
    bound["content_digest"] = _candidate_digest(bound)
    candidate_bytes = canonical_json_bytes(bound) + b"\n"
    card_bytes = (
        package.dataset_card_text.rstrip()
        + "\n\n## Canonical publication controls\n\n"
        + f"Release manifest digest: `{package.manifest_digest}`\n\n"
        + f"Candidate digest: `{bound['content_digest']}`\n\n"
        + f"Source-rights receipt digest: `{rights_digest}`\n\n"
        + f"Staging plan digest: `{plan.plan_digest}`\n\n"
        + f"Policy binding digest: `{proof_digest}`\n"
    ).encode("utf-8")
    if (root / SOURCE_RIGHTS_RELPATH).read_bytes() != rights_bytes:
        raise FederalRegisterPublicationPackageError(
            "canonical rights receipt changed during Federal control creation"
        )
    _atomic_write_canonical_controls(
        root,
        {
            runtime.FEDERAL_CANDIDATE_MANIFEST_RELPATH: candidate_bytes,
            runtime.FEDERAL_DATASET_CARD_RELPATH: card_bytes,
        },
    )
    return FederalRegisterCanonicalControlBundle(
        phase="federal_staging",
        candidate_manifest_digest=str(bound["content_digest"]),
        staging_candidate_digest=staging_digest,
        candidate_path=runtime.FEDERAL_CANDIDATE_MANIFEST_RELPATH,
        dataset_card_path=runtime.FEDERAL_DATASET_CARD_RELPATH,
        dataset_card_sha256=sha256(card_bytes).hexdigest(),
        release_manifest_digest=package.manifest_digest,
        plan_digest=plan.plan_digest,
        policy_proof_digest=proof_digest,
        source_rights_receipt_digest=rights_digest,
        staging_revision="",
    )


def materialize_federal_register_main_controls(
    package: FederalRegisterPublicationPackage,
    plan: PublicationPlan,
    *,
    repository_root: str | Path,
    staging_revision: str,
    sealed_at: str,
) -> FederalRegisterCanonicalControlBundle:
    """Promote only Federal publication binding and write the main seal/card."""

    from ipfs_datasets_py.processors.legal_data import (
        legal_corpora_publication_runtime as runtime,
    )
    from ipfs_datasets_py.processors.legal_data.state_laws_publication_package import (
        _atomic_write_canonical_controls,
        _canonical_control_receipt,
    )

    root = Path(repository_root).expanduser()
    revision = _git_sha(staging_revision, label="staging_revision")
    if (
        plan.target_revision != "main"
        or plan.repository_id != DEFAULT_DATASET_REPO_ID
        or plan.release_sha256 != package.manifest_digest
    ):
        raise FederalRegisterPublicationPackageError(
            "Federal main controls require the exact protected main plan"
        )
    _, _, rights_digest = _canonical_rights(root, package)
    candidate, _ = _read_json(
        root / runtime.FEDERAL_CANDIDATE_MANIFEST_RELPATH,
        label="canonical Federal staging candidate",
    )
    binding = candidate.get("publication_binding")
    if not isinstance(binding, Mapping):
        raise FederalRegisterPublicationPackageError(
            "Federal staging candidate lacks its exact publication binding"
        )
    declared_candidate_digest = _digest(
        candidate.get("content_digest"),
        label="Federal staging candidate content_digest",
    )
    if _candidate_digest(candidate) != declared_candidate_digest:
        raise FederalRegisterPublicationPackageError(
            "Federal staging candidate content digest is invalid"
        )
    staging_digest = _digest(
        binding.get("staging_candidate_digest"),
        label="staging candidate digest",
    )
    base = dict(candidate)
    base["publication_binding"] = None
    base.pop("plan_digest", None)
    base.pop("policy_proof_digest", None)
    base["content_digest"] = _candidate_digest(base)
    if base["content_digest"] != staging_digest:
        raise FederalRegisterPublicationPackageError(
            "Federal staging candidate identity chain is invalid"
        )
    canary, _ = _read_json(
        root / STAGING_CANARY_RELPATH,
        label="canonical Federal staging canary",
    )
    if (
        canary.get("status") != "passed"
        or canary.get("fixture_only") is not False
        or canary.get("dirty") is not False
        or canary.get("live_staging") is not True
        or canary.get("dataset_repo_id") != DEFAULT_DATASET_REPO_ID
        or canary.get("staging_revision") != revision
        or canary.get("final_manifest_digest") != staging_digest
        or canary.get("release_manifest_digest") != package.manifest_digest
        or canary.get("plan_digest") != binding.get("plan_digest")
        or canary.get("policy_proof_digest")
        != binding.get("policy_proof_digest")
    ):
        raise FederalRegisterPublicationPackageError(
            "Federal staging canary does not bind candidate A, its staging "
            "plan/proof, release bytes, and immutable revision"
        )
    proof_digest = canonical_legal_corpora_policy_proof_digest(
        phase="federal_main",
        candidate_manifest_digest=staging_digest,
        plan=plan,
    )
    promoted = dict(base)
    promoted["plan_digest"] = plan.plan_digest
    promoted["policy_proof_digest"] = proof_digest
    promoted["publication_binding"] = {
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": proof_digest,
        "release_manifest_digest": package.manifest_digest,
        "staging_candidate_digest": staging_digest,
    }
    promoted["content_digest"] = _candidate_digest(promoted)
    runtime.parse_utc_z(sealed_at, name="sealed_at")
    seal_payload = {
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "created_after_mutation": False,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "dirty": False,
        "final_manifest_digest": promoted["content_digest"],
        "fixture_only": False,
        "goal_id": "LCR-G140",
        "live_staging": True,
        "manifest_digest": promoted["content_digest"],
        "mutation_executed": False,
        "network_mutation": False,
        "no_mutation": True,
        "no_mutate": True,
        "operation": "additive_main_upload",
        "phase": "federal_main",
        "plan_digest": plan.plan_digest,
        "policy_proof_digest": proof_digest,
        "post_hoc": False,
        "present": True,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "producer": "seal_federal_register_prepublication.py",
        "program_id": "legal-corpora-reindex-v1",
        "release_manifest_digest": package.manifest_digest,
        "schema": runtime.SEAL_SCHEMA_V1,
        "sealed_at": sealed_at,
        "staging_revision": revision,
        "status": "sealed",
        "target_repo": DEFAULT_DATASET_REPO_ID,
        "task_id": "LCR-073",
        "timing": "before_mutation",
    }
    _, seal_digest, seal_bytes = _canonical_control_receipt(seal_payload)
    card_bytes = (
        package.dataset_card_text.rstrip()
        + "\n\n## Canonical publication controls\n\n"
        + f"Release manifest digest: `{package.manifest_digest}`\n\n"
        + f"Candidate digest: `{promoted['content_digest']}`\n\n"
        + f"Staging candidate digest: `{staging_digest}`\n\n"
        + f"Source-rights receipt digest: `{rights_digest}`\n\n"
        + f"Main plan digest: `{plan.plan_digest}`\n\n"
        + f"Policy binding digest: `{proof_digest}`\n\n"
        + f"Verified staging commit: `{revision}`\n"
    ).encode("utf-8")
    candidate_bytes = canonical_json_bytes(promoted) + b"\n"
    _atomic_write_canonical_controls(
        root,
        {
            runtime.FEDERAL_CANDIDATE_MANIFEST_RELPATH: candidate_bytes,
            runtime.FEDERAL_DATASET_CARD_RELPATH: card_bytes,
            runtime.FEDERAL_PREPUBLICATION_SEAL_RELPATH: seal_bytes,
        },
    )
    return FederalRegisterCanonicalControlBundle(
        phase="federal_main",
        candidate_manifest_digest=str(promoted["content_digest"]),
        staging_candidate_digest=staging_digest,
        candidate_path=runtime.FEDERAL_CANDIDATE_MANIFEST_RELPATH,
        dataset_card_path=runtime.FEDERAL_DATASET_CARD_RELPATH,
        dataset_card_sha256=sha256(card_bytes).hexdigest(),
        release_manifest_digest=package.manifest_digest,
        plan_digest=plan.plan_digest,
        policy_proof_digest=proof_digest,
        source_rights_receipt_digest=rights_digest,
        staging_revision=revision,
        seal_path=runtime.FEDERAL_PREPUBLICATION_SEAL_RELPATH,
        seal_content_digest=seal_digest,
    )


__all__ = [
    "DEFAULT_STAGING_BRANCH",
    "FederalRegisterCanonicalControlBundle",
    "FederalRegisterPublicationPackage",
    "FederalRegisterPublicationPackageError",
    "federal_register_publication_profile",
    "materialize_federal_register_main_controls",
    "materialize_federal_register_release_tree",
    "materialize_federal_register_staging_controls",
    "plan_federal_register_publication_dry_run",
    "prepare_federal_register_publication_package",
]
