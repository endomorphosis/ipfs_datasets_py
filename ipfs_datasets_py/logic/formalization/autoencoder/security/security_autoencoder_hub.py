"""Pinned distribution and local catalog registration of security advisory weights.

Network writes require the native publisher's exact PublicationApproval. No
repository is created, visibility changed, or runtime pointer promoted here.
Downloaded JSON is inert; the installed portable loader owns model semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

HUB_SCHEMA = "security-autoencoder-hub@1"
HUB_FIELDS = frozenset({"schema", "repository_id", "repository_type", "revision", "release_prefix", "manifest_sha256"})
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MANIFEST = "release-manifest.json"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value, length=64):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{%d}" % length, value) is None:
        raise ValueError("exact lowercase immutable digest required")
    return value


def _repository(value):
    if (type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value) is None
            or "security" not in value.split("/")[1].lower()
            or any(word in value.lower() for word in ("legal", "shared-weights", "shared_weights"))):
        raise ValueError("explicit separate security model repository required")
    return value


def validate_hub_descriptor(descriptor):
    if (type(descriptor) is not dict or set(descriptor) != HUB_FIELDS
            or descriptor["schema"] != HUB_SCHEMA or descriptor["repository_type"] != "model"):
        raise ValueError("closed security model Hub descriptor required")
    _repository(descriptor["repository_id"])
    _digest(descriptor["revision"], 40)
    _digest(descriptor["manifest_sha256"])
    if (type(descriptor["release_prefix"]) is not str
            or re.fullmatch(r"releases/[a-z0-9][a-z0-9_-]{0,95}", descriptor["release_prefix"]) is None):
        raise ValueError("immutable security release prefix required")
    return dict(descriptor)


def _directory(path):
    path = Path(path).absolute()
    if (path.resolve() != path or any(part.lower() in {"legal-ir", "legal_ir", "legalir", "shared-weights", "shared_weights"}
                                      for part in path.parts)):
        raise ValueError("separate canonical security cache required")
    return path


def _read(path, maximum=MAX_FILE_BYTES):
    path = Path(path)
    if path.parent.resolve(strict=True) != path.parent.absolute():
        raise ValueError("symlinked security package parent refused")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
            raise ValueError("bounded single-link security package file required")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        if (len(raw) > maximum or any(getattr(before, field) != getattr(after, field)
                for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))):
            raise ValueError("security package changed during read")
        return raw
    finally:
        os.close(fd)


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate security manifest field")
        out[key] = value
    return out


def _manifest(raw, expected):
    from .security_autoencoder_checkpoint import PACKAGE_FILES
    if type(raw) is not bytes or not 0 < len(raw) <= 256_000 or _sha(raw) != _digest(expected):
        raise ValueError("pinned security manifest differs")
    value = json.loads(raw, object_pairs_hook=_unique)
    if (type(value) is not dict or value.get("schema") != "security-autoencoder-release@1"
            or value.get("domain") != "security-code@1" or value.get("authority") != "unverified_candidate_only"
            or value.get("model_scope") != "benchmark_informed_development" or value.get("holdout_evaluated") is not False
            or type(value.get("files")) is not dict or set(value["files"]) != set(PACKAGE_FILES) - {MANIFEST}):
        raise ValueError("closed development security package manifest required")
    total = len(raw)
    for name, binding in value["files"].items():
        if (type(binding) is not dict or set(binding) != {"sha256", "bytes"}
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= MAX_FILE_BYTES):
            raise ValueError("bounded exact security payload binding required")
        _digest(binding["sha256"])
        total += binding["bytes"]
    if total > MAX_PACKAGE_BYTES:
        raise ValueError("security package exceeds byte budget")
    return value


def _release_inventory(raw, expected, release_id):
    manifest = _manifest(raw, expected)
    entries = [{"path": name, "size_bytes": item["bytes"], "sha256": item["sha256"]}
               for name, item in manifest["files"].items()]
    entries.append({"path": MANIFEST, "size_bytes": len(raw), "sha256": expected})
    return {"release_id": release_id, "release_sha256": expected, "files": sorted(entries, key=lambda row: row["path"])}


def security_publication_profile(repository_id):
    from ipfs_datasets_py.huggingface.publication_profile import HuggingFacePublicationProfile
    return HuggingFacePublicationProfile(profile_id="security-autoencoder-development",
        program_id="security-autoencoder-advisor", goal_id="SECURITY-AE-PUBLISH",
        plan_schema_version="security-autoencoder-hf-publication-plan/v1",
        receipt_schema_version="security-autoencoder-hf-publication-receipt/v1",
        repository_id=_repository(repository_id), repository_type="model",
        release_prefix_template="releases/{release_id}", pointer_path="runtime/security-autoencoder.json",
        commit_message="Append immutable experimental security advisory checkpoint",
        metadata={"authority": "unverified_candidate_only", "development_only": True})


def _publisher(repository_id, *, api=None, fetch_bytes=None):
    from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher
    return HuggingFaceReleasePublisher(profile=security_publication_profile(repository_id),
        api=api, fetch_bytes=fetch_bytes, pinned_download_workers=1)


def _fetch_bytes(repository_id, revision, remote_path):
    """Use standard Hub credential resolution; never print headers or response bodies."""
    from huggingface_hub import hf_hub_url
    from huggingface_hub.utils import build_hf_headers
    import requests
    try:
        with requests.get(hf_hub_url(repository_id, remote_path, repo_type="model", revision=revision),
                          headers=build_hf_headers(), stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            pieces, total = [], 0
            for piece in response.iter_content(chunk_size=65536):
                total += len(piece)
                if total > MAX_FILE_BYTES:
                    raise ValueError("download exceeds security package file bound")
                pieces.append(piece)
            return b"".join(pieces)
    except Exception as exc:
        raise ValueError("pinned security Hub download failed: " + type(exc).__name__) from None


def _loaded(package, manifest_sha256):
    from .security_autoencoder_checkpoint import load_security_checkpoint
    return load_security_checkpoint(Path(package), expected_manifest_sha256=manifest_sha256)


def _probe(loaded):
    from .security_autoencoder_checkpoint import score_security_observations
    fixture = loaded["inference_fixture"]
    result = score_security_observations(checkpoint=loaded["descriptor"], observations=fixture["observations"])
    # The strict loader already verifies the numeric fixture. Call inference
    # again at registration rather than advertising unexecuted availability.
    if not result.get("rows"):
        raise ValueError("security model probe produced no advisory rows")
    return {"executed": True, "input_sha256": _sha(_json(fixture["observations"])),
            "result_sha256": _sha(_json(result)), "row_count": len(result["rows"]),
            "provider_calls": 0, "training_steps": 0, "proof_authority": False}


def download_security_checkpoint(*, descriptor, cache_root, fetch_bytes=None, local_files_only=False):
    """Resolve a full-commit package into a verified immutable local cache."""
    if type(local_files_only) is not bool:
        raise ValueError("explicit local-files-only boolean required")
    hub = validate_hub_descriptor(descriptor)
    root = _directory(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ValueError("security cache must be a directory")
    target = root / ("security-autoencoder-" + hub["manifest_sha256"])
    cache_hit = target.exists()
    downloaded_files = 0
    if cache_hit:
        if target.is_symlink() or any(p.is_symlink() or p.stat().st_mode & 0o222 for p in target.iterdir()):
            raise ValueError("security cache is mutable or contains links")
        loaded = _loaded(target, hub["manifest_sha256"])
    else:
        if local_files_only:
            raise ValueError("pinned security checkpoint is absent from offline cache")
        fetch = fetch_bytes or _fetch_bytes
        raw = fetch(hub["repository_id"], hub["revision"], hub["release_prefix"] + "/" + MANIFEST)
        inventory = _release_inventory(raw, hub["manifest_sha256"], hub["release_prefix"].split("/")[1])
        publisher = _publisher(hub["repository_id"], fetch_bytes=fetch)
        plan = publisher.plan_dry_run(inventory)
        temporary = Path(tempfile.mkdtemp(prefix=".security-fetch-", dir=root))
        try:
            verification = publisher.redownload_and_validate_pinned(commit_sha=hub["revision"], plan=plan,
                cache_root=temporary / "download")
            package = temporary / "download" / hub["release_prefix"]
            _loaded(package, hub["manifest_sha256"])
            for path in package.iterdir():
                path.chmod(0o444)
            package.rename(target)
            target.chmod(0o555)
            downloaded_files = verification.revalidated_file_count + 1
        finally:
            shutil.rmtree(temporary)
        loaded = _loaded(target, hub["manifest_sha256"])
    return {"schema": "security-autoencoder-hub-resolution@1", "hub": hub,
        "package": str(target), "manifest_sha256": hub["manifest_sha256"], "checkpoint": loaded["descriptor"],
        "cache_hit": cache_hit, "downloaded_files": downloaded_files,
        "frozen_inference": True, "training_steps": 0, "provider_calls": 0, "proof_authority": False}


@dataclass(frozen=True)
class SecurityCheckpointPublication:
    package: Path
    manifest_sha256: str
    private: bool
    plan: object

    def to_dict(self):
        return {"schema": "security-autoencoder-publication-proposal@1", "package": str(self.package),
            "manifest_sha256": self.manifest_sha256, "private": self.private, "repository_creation_performed": False,
            "plan": self.plan.to_dict(), "authority": "unverified_candidate_only",
            "checkpoint_uploaded": False, "runtime_promoted": False}


def plan_security_checkpoint_publication(*, package, expected_manifest_sha256, repository_id,
                                        audited_parent_commit="", private=True):
    """Produce an offline exact native plan; no API or credential is consulted."""
    if type(private) is not bool:
        raise ValueError("explicit repository visibility required")
    package = _directory(package)
    loaded = _loaded(package, expected_manifest_sha256)
    _probe(loaded)
    if not private:
        review = loaded.get("provenance_review", {})
        if (review.get("schema") != "security-autoencoder-public-provenance-review@1"
                or review.get("review_status") != "reviewed_with_explicit_lineage_limits"
                or review.get("requested_visibility") != "public"
                or review.get("release_kind") != "experimental_benchmark_informed_development"
                or review.get("proposed_repository") != repository_id or not loaded.get("model_card")):
            raise ValueError("public security release requires the package-bound provenance review and model card")
    raw = _read(package / MANIFEST, 256_000)
    inventory = _release_inventory(raw, expected_manifest_sha256, "sha256-" + expected_manifest_sha256)
    publisher = _publisher(repository_id)
    plan = publisher.plan_dry_run(inventory, local_root=package, audited_parent_commit=audited_parent_commit)
    plan = replace(plan, metadata={**plan.metadata, "private": private,
        "authority": "unverified_candidate_only", "model_scope": "benchmark_informed_development"})
    return SecurityCheckpointPublication(package, expected_manifest_sha256, private, plan)


def publish_security_checkpoint(*, publication, approval, api, verification_root, fetch_bytes=None):
    """Publish an exact reviewed plan, then redownload and load its immutable pin.

    The caller supplies a native PublicationApproval tied to the concrete plan.
    This function cannot manufacture approval or create/alter repository state
    beyond the native append-only release commit.
    """
    from ipfs_datasets_py.huggingface.publisher import PublicationApproval
    if type(publication) is not SecurityCheckpointPublication or type(approval) is not PublicationApproval:
        raise ValueError("exact publication proposal and native approval required")
    plan = publication.plan
    fresh = plan_security_checkpoint_publication(package=publication.package,
        expected_manifest_sha256=publication.manifest_sha256, repository_id=plan.repository_id,
        audited_parent_commit=plan.audited_parent_commit, private=publication.private)
    if fresh.to_dict() != publication.to_dict() or approval.plan_digest != plan.plan_digest:
        raise ValueError("security publication proposal or approval drifted")
    # Read-only check: the caller must create the approved repository separately.
    info = api.repo_info(repo_id=plan.repository_id, repo_type="model", revision="main")
    if getattr(info, "private", None) is not publication.private:
        raise ValueError("security repository visibility differs from reviewed plan")
    root = _directory(verification_root)
    if root.exists():
        raise ValueError("fresh security readback directory required")
    publisher = _publisher(plan.repository_id, api=api, fetch_bytes=fetch_bytes or _fetch_bytes)
    committed = publisher.publish_append_only(plan, approval=approval, local_root=publication.package)
    readback = publisher.redownload_and_validate_pinned(commit_sha=committed.commit_sha,
        plan=plan, cache_root=root)
    package = root / plan.release_prefix
    loaded = _loaded(package, publication.manifest_sha256)
    probe = _probe(loaded)
    remote = {}
    for item in plan.operations:
        raw = _read(root / item.remote_path)
        remote[item.remote_path] = {"sha256": _sha(raw), "size_bytes": len(raw), "commit_sha": committed.commit_sha}
    verified = publisher.verify_post_publication(commit_receipt=committed, plan=plan, remote_objects=remote)
    hub = validate_hub_descriptor({"schema": HUB_SCHEMA, "repository_type": "model",
        "repository_id": plan.repository_id, "revision": committed.commit_sha,
        "release_prefix": plan.release_prefix, "manifest_sha256": publication.manifest_sha256})
    native_receipt = publisher.build_publication_receipt(plan=plan, commit_receipt=committed,
        post_publication=verified, pinned_redownload=readback, approval=approval,
        status="published_pending_promotion")
    # The generic receipt assumes signed manifests for other publication
    # profiles. This inert development package has approval/digest binding,
    # not a cryptographic manifest signature.
    native_receipt["evidence"]["signed_reviewed_release_manifest"] = False
    native_receipt["evidence"]["reviewed_manifest_bound_to_approval"] = True
    return {"schema": "security-autoencoder-publication@1", "hub": hub, "package": str(package),
        "private": publication.private, "checkpoint_uploaded": True, "pinned_readback_verified": True,
        "checkpoint": loaded["descriptor"], "inference_probe": probe,
        "native_publication": native_receipt,
        "runtime_promoted": False, "proof_authority": False, "completion_authority": False}
