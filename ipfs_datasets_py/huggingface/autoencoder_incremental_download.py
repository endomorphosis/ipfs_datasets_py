"""Pinned campaign weight bootstrap and resumable sparse replay.

Only explicitly selected artifacts in the authorized campaign dataset transfer.
Downloads verify immutable byte identities before replay; remote qualification
receipts remain historical evidence, never local qualification or promotion.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
from urllib.parse import urlsplit

from . import autoencoder_incremental as publication

SEED_SCHEMA = "autoencoder-campaign-seed/v1"
DOWNLOAD_SCHEMA = "autoencoder-campaign-download/v1"
MAX_ANCHOR_BYTES = 512 * 1024 * 1024
MAX_REFERENCE_DEPTH = 8
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST = re.compile(r"autoformal/uscode/autoencoders/[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*/[0-9a-f]{64}/lanes/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/versions/[0-9a-f]{64}/[0-9a-f]{64}/update\.json\Z")


class CampaignDownloadError(publication.IncrementalPublicationError):
    """An artifact is unbound, altered, oversized or outside the campaign."""


def _binding(repository_id: str, commit_sha: str) -> None:
    if repository_id != publication.REPOSITORY or not isinstance(commit_sha, str) or not _COMMIT.fullmatch(commit_sha):
        raise CampaignDownloadError("campaign downloads require the authorized repository and immutable commit")


def _anchor_path(ref: Mapping[str, Any]) -> str:
    return f"{publication.PREFIX}/anchors/{ref['sha256']}.state.json"


def publish_seed_checkpoint(checkpoint_path: str | Path, *, expected_artifact: Mapping[str, Any],
                            upload: bool = False, api: Any = None) -> dict[str, Any]:
    """Append one explicitly hashed baseline, with no qualification authority.

    Exact remote metadata makes repeated or ambiguous calls idempotent. The
    original local checkpoint is only read, never rewritten or replaced.
    """
    ref = publication.sparse.artifact_ref(expected_artifact)
    if ref["bytes"] > MAX_ANCHOR_BYTES:
        raise CampaignDownloadError("campaign anchor exceeds byte bound")
    path = Path(checkpoint_path).absolute()
    raw = publication._read(path, MAX_ANCHOR_BYTES, ref)
    resolved = publication.sparse.resolve_checkpoint(ref, resolver=lambda _: path)
    if resolved.manifest is not None:
        raise CampaignDownloadError("campaign seed must be a full checkpoint")
    remote_path = _anchor_path(ref)
    metadata = {"schema": SEED_SCHEMA, "repository_id": publication.REPOSITORY,
                "path_in_repo": remote_path, "artifact": ref,
                "transport_baseline_only": True, "qualified": False,
                "admitted": False, "formalized": False, "promoted": False}
    snapshots = {remote_path: raw, remote_path.removesuffix(".state.json") + ".seed.json": publication._json(metadata)}
    result = {**metadata, "uploaded": False, "dry_run": not upload, "remote_anchor": None}
    if not upload:
        return result
    from huggingface_hub import CommitOperationAdd, HfApi
    api = api or HfApi()
    parent = str(api.repo_info(repo_id=publication.REPOSITORY, repo_type="dataset").sha)
    _binding(publication.REPOSITORY, parent)
    present = set()
    for remote in api.get_paths_info(publication.REPOSITORY, list(snapshots), repo_type="dataset", revision=parent):
        key = str(getattr(remote, "path", "") or getattr(remote, "rfilename", ""))
        if key not in snapshots or key in present or not publication._matches(remote, snapshots[key]):
            raise CampaignDownloadError("immutable campaign seed conflicts with remote metadata")
        present.add(key)
    operations = [CommitOperationAdd(path_in_repo=key, path_or_fileobj=value)
                  for key, value in snapshots.items() if key not in present]
    if operations:
        committed = api.create_commit(repo_id=publication.REPOSITORY, repo_type="dataset",
            operations=operations, parent_commit=parent,
            commit_message="Append exact campaign transport baseline; unqualified seed")
        commit = str(getattr(committed, "oid", "") or (committed.get("oid", "") if isinstance(committed, Mapping) else ""))
    else:
        commit = parent
    _binding(publication.REPOSITORY, commit)
    verified = set()
    for remote in api.get_paths_info(publication.REPOSITORY, list(snapshots), repo_type="dataset", revision=commit):
        key = str(getattr(remote, "path", "") or getattr(remote, "rfilename", ""))
        if key not in snapshots or key in verified or not publication._matches(remote, snapshots[key]):
            raise CampaignDownloadError("pinned campaign seed verification failed")
        verified.add(key)
    if verified != set(snapshots):
        raise CampaignDownloadError("pinned campaign seed is missing")
    anchor = {"repository_id": publication.REPOSITORY, "commit_sha": commit,
              "path_in_repo": remote_path, **ref}
    return {**result, "uploaded": True, "dry_run": False, "commit_sha": commit,
            "remote_already_present": not operations, "remote_anchor": anchor,
            "anchor_reference": anchor}


class HubCampaignArtifactClient:
    """Disk streaming with metadata and byte bounds; no pretrained resolver."""

    def __init__(self, api: Any = None, *, timeout_seconds: float = 30):
        from huggingface_hub import HfApi
        if not 0 < timeout_seconds <= 60:
            raise CampaignDownloadError("download timeout must be in (0, 60]")
        self.api = api or HfApi()
        self.timeout = timeout_seconds
        if self.api.endpoint.rstrip("/") != "https://huggingface.co":
            raise CampaignDownloadError("campaign transport requires the Hugging Face endpoint")

    def fetch(self, repository_id, commit_sha, path_in_repo, destination, *, max_bytes):
        from huggingface_hub import get_hf_file_metadata, hf_hub_url
        from huggingface_hub.utils import get_session, hf_raise_for_status
        _binding(repository_id, commit_sha)
        url = hf_hub_url(repository_id, path_in_repo, repo_type="dataset", revision=commit_sha)
        metadata = get_hf_file_metadata(url, token=self.api.token, timeout=self.timeout)
        if (metadata.commit_hash != commit_sha or type(metadata.size) is not int
                or not 0 < metadata.size <= max_bytes):
            raise CampaignDownloadError("remote metadata differs from pinned commit or byte bound")
        location = metadata.location
        if urlsplit(location).scheme != "https":
            raise CampaignDownloadError("campaign artifact location must use HTTPS")
        # Signed CDN URLs authorize themselves; never send the Hub credential
        # to a different origin. Requests also strips it on cross-host redirects.
        headers = self.api._build_hf_headers() if urlsplit(location).netloc == "huggingface.co" else {}
        count = 0
        with get_session().get(location, headers=headers, stream=True, timeout=self.timeout) as response:
            hf_raise_for_status(response)
            if response.status_code != 200:
                raise CampaignDownloadError("unexpected artifact download response")
            with Path(destination).open("xb") as output:
                for block in response.iter_content(1024 * 1024):
                    count += len(block)
                    if count > metadata.size or count > max_bytes:
                        raise CampaignDownloadError("artifact download exceeds pinned byte bound")
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
        if count != metadata.size:
            raise CampaignDownloadError("artifact download is incomplete")
        return Path(destination)


@contextmanager
def _owner(destination):
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / ".download.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CampaignDownloadError("download destination already has an owner") from exc
        yield


def _cached_fetch(client, repository_id, revision, remote, local, maximum, root, telemetry,
                  *, ref=None, digest=None, weight=False):
    if local.exists() or local.is_symlink():
        raw = publication._read(local, maximum, ref)
        if digest is not None and publication._sha(raw) != digest:
            raise CampaignDownloadError("retained manifest hash differs")
        telemetry["reused_files"] += 1
        return raw
    descriptor, temporary_name = tempfile.mkstemp(prefix=".artifact-", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        got = Path(client.fetch(repository_id, revision, remote, temporary, max_bytes=maximum)).absolute()
        if got != temporary:
            raise CampaignDownloadError("transport changed the owned destination")
        raw = publication._read(temporary, maximum, ref)
        if digest is not None and publication._sha(raw) != digest:
            raise CampaignDownloadError("downloaded manifest hash differs")
        publication._write(local, raw)
        telemetry["downloaded_bytes"] += len(raw)
        telemetry["downloaded_files"] += 1
        telemetry["downloaded_weight_files"] += int(weight)
        return raw
    finally:
        temporary.unlink(missing_ok=True)


def download_seed_checkpoint(anchor_reference: Mapping[str, Any], destination: str | Path,
                             *, api: Any = None, client: Any = None) -> dict[str, Any]:
    """Verify and parse a campaign baseline before first-generation training.

    Preserve the full checkpoint's physical bytes, including legacy formatting;
    parsing does not turn a baseline into a locally qualified model.
    """
    _reference_plan(anchor_reference)
    if anchor_reference.get("kind", "anchor") != "anchor":
        raise CampaignDownloadError("seed download requires a direct anchor reference")
    repository = anchor_reference.get("repository_id")
    commit = anchor_reference.get("commit_sha")
    _binding(repository, commit)
    ref = publication.sparse.artifact_ref(anchor_reference)
    if ref["bytes"] > MAX_ANCHOR_BYTES or anchor_reference.get("path_in_repo") != _anchor_path(ref):
        raise CampaignDownloadError("seed reference differs from bounded campaign anchor path")
    root = Path(destination).absolute()
    client = client or HubCampaignArtifactClient(api)
    telemetry = {"downloaded_bytes": 0, "downloaded_files": 0, "reused_files": 0,
                 "downloaded_weight_files": 0}
    with _owner(root):
        path = root / "anchors" / (ref["sha256"] + ".state.json")
        _cached_fetch(client, repository, commit, anchor_reference["path_in_repo"], path,
                      ref["bytes"], root, telemetry, ref=ref, weight=True)
        resolved = publication.sparse.resolve_checkpoint(ref, resolver=lambda _: path)
        if resolved.manifest is not None:
            raise CampaignDownloadError("first-generation seed must be a full checkpoint")
        result = {"schema": DOWNLOAD_SCHEMA, "repository_id": repository, "commit_sha": commit,
                  "anchor_checkpoint": ref, "anchor_path": str(path),
                  "materialized_checkpoint": ref, "materialized_checkpoint_artifact": ref,
                  "materialized_checkpoint_path": str(path), "state_identity": resolved.state_identity,
                  "checkpoint_parsed": True, "hash_verified": True, "transport_baseline_only": True,
                  "campaign_reference_depth": 0,
                  "weights_downloaded": telemetry["downloaded_weight_files"] > 0,
                  "locally_qualified": False, "registration_performed": False,
                  "promotion_performed": False, "admitted": False, "formalized": False, **telemetry}
        publication._write(root / "receipts" / (publication._sha(publication._json(result)) + ".json"), publication._json(result))
        return result


def _reference_plan(reference, *, expected_artifact=None, seen=(), depth=0):
    """Validate the entire portable chain without following network pointers."""
    if not isinstance(reference, Mapping):
        raise CampaignDownloadError("campaign anchor reference must be a mapping")
    _binding(reference.get("repository_id"), reference.get("commit_sha"))
    ref = publication.sparse.artifact_ref(reference)
    kind = reference.get("kind", "anchor")
    if kind == "anchor":
        if (ref["bytes"] > MAX_ANCHOR_BYTES or reference.get("path_in_repo") != _anchor_path(ref)
                or (expected_artifact is not None and ref != expected_artifact)
                or ("materialized_checkpoint" in reference and reference["materialized_checkpoint"] != ref)):
            raise CampaignDownloadError("direct anchor is not the exact campaign seed")
        return depth
    if kind != "sparse":
        raise CampaignDownloadError("unknown campaign anchor reference kind")
    path = reference.get("path_in_repo")
    if (ref["bytes"] > publication.MAX_MANIFEST_BYTES or not isinstance(path, str)
            or not _MANIFEST.fullmatch(path) or ".." in path):
        raise CampaignDownloadError("invalid sparse ancestor manifest reference")
    if ref["sha256"] in seen:
        raise CampaignDownloadError("cyclic sparse campaign reference")
    if depth >= MAX_REFERENCE_DEPTH:
        raise CampaignDownloadError("sparse campaign reference depth exceeds bound")
    materialized = publication.sparse.artifact_ref(reference.get("materialized_checkpoint"))
    if (materialized["bytes"] > MAX_ANCHOR_BYTES
            or (expected_artifact is not None and materialized != expected_artifact)):
        raise CampaignDownloadError("sparse ancestor materialized hash differs from child anchor")
    return _reference_plan(reference.get("anchor_reference"), seen=(*seen, ref["sha256"]), depth=depth + 1)


def resolve_campaign_anchor(anchor_reference: Mapping[str, Any], destination: str | Path, *,
        expected_artifact: Mapping[str, Any] | None = None, api=None, client=None,
        _ancestor_manifests=(), _local_anchor_resolver=None) -> dict[str, Any]:
    """Resolve a bounded portable seed/sparse chain to exact local full bytes."""
    expected = publication.sparse.artifact_ref(expected_artifact) if expected_artifact is not None else None
    _reference_plan(anchor_reference, expected_artifact=expected,
                    seen=_ancestor_manifests, depth=len(_ancestor_manifests))
    if anchor_reference.get("kind", "anchor") == "anchor":
        return download_seed_checkpoint(anchor_reference, destination, api=api, client=client)
    ref = publication.sparse.artifact_ref(anchor_reference)
    result = _download_sparse_update(anchor_reference["repository_id"], anchor_reference["commit_sha"],
        anchor_reference["path_in_repo"], ref["sha256"], destination,
        anchor_reference=anchor_reference["anchor_reference"], api=api, client=client,
        local_anchor_resolver=_local_anchor_resolver,
        _ancestor_manifests=_ancestor_manifests, _expected_manifest_bytes=ref["bytes"])
    if result["materialized_checkpoint"] != anchor_reference["materialized_checkpoint"]:
        raise CampaignDownloadError("reconstructed sparse ancestor differs from declared full anchor")
    if expected is not None and result["materialized_checkpoint"] != expected:
        raise CampaignDownloadError("reconstructed sparse ancestor differs from child anchor")
    return result


def download_sparse_update(repository_id: str, commit_sha: str, manifest_path: str,
        expected_manifest_sha256: str, destination: str | Path, *,
        anchor_reference: Mapping[str, Any] | None = None, local_anchor_resolver=None,
        api: Any = None, client: Any = None) -> dict[str, Any]:
    """Fetch exact selected update, reuse verified files, replay to local state.

    ``client.fetch(repo, commit, remote_path, destination, max_bytes=...)`` is
    the bounded transport seam. ``anchor_reference`` explicitly authorizes one
    direct full baseline or bounded sparse ancestry; without it a verified local
    anchor is mandatory. A supplied local resolver takes precedence after the
    portable chain is validated. Only a returned ``None`` permits remote
    fallback; altered local bytes fail closed.
    This never registers versions or advances local or remote model heads.
    """
    return _download_sparse_update(repository_id, commit_sha, manifest_path,
        expected_manifest_sha256, destination, anchor_reference=anchor_reference,
        local_anchor_resolver=local_anchor_resolver, api=api, client=client)


def _download_sparse_update(repository_id: str, commit_sha: str, manifest_path: str,
        expected_manifest_sha256: str, destination: str | Path, *,
        anchor_reference=None, local_anchor_resolver=None, api=None, client=None,
        _ancestor_manifests=(), _expected_manifest_bytes=None) -> dict[str, Any]:
    _binding(repository_id, commit_sha)
    if (not isinstance(manifest_path, str) or not _MANIFEST.fullmatch(manifest_path)
            or ".." in manifest_path or not isinstance(expected_manifest_sha256, str)
            or not _SHA.fullmatch(expected_manifest_sha256)):
        raise CampaignDownloadError("invalid pinned campaign manifest selection")
    if expected_manifest_sha256 in _ancestor_manifests:
        raise CampaignDownloadError("cyclic sparse campaign reference")
    if len(_ancestor_manifests) >= MAX_REFERENCE_DEPTH:
        raise CampaignDownloadError("sparse campaign reference depth exceeds bound")
    chain = (*_ancestor_manifests, expected_manifest_sha256)
    root = Path(destination).absolute()
    client = client or HubCampaignArtifactClient(api)
    telemetry = {"downloaded_bytes": 0, "downloaded_files": 0, "reused_files": 0,
                 "downloaded_weight_files": 0}

    def fetch(remote, local, maximum, *, ref=None, digest=None, revision=commit_sha, weight=False):
        return _cached_fetch(client, repository_id, revision, remote, local, maximum, root,
                             telemetry, ref=ref, digest=digest, weight=weight)

    with _owner(root):
        local_manifest = root / ("update-" + expected_manifest_sha256 + ".json")
        raw = fetch(manifest_path, local_manifest, publication.MAX_MANIFEST_BYTES,
                    digest=expected_manifest_sha256)
        if _expected_manifest_bytes is not None and len(raw) != _expected_manifest_bytes:
            raise CampaignDownloadError("sparse ancestor manifest size differs")
        manifest = publication._object(raw)
        if (manifest.get("schema") != publication.SCHEMA or publication._json(manifest) != raw
                or manifest.get("path_in_repo") != manifest_path or manifest.get("repository_id") != repository_id):
            raise CampaignDownloadError("manifest differs from selected publication binding")
        files = manifest.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= publication.MAX_FILES:
            raise CampaignDownloadError("manifest exceeds artifact count bound")
        planned, seen, total = [], set(), 0
        for item in files:
            ref = publication.sparse.artifact_ref(item)
            kind = item.get("kind")
            if kind not in publication._KINDS or item.get("path_in_repo") != publication._remote(ref, kind):
                raise CampaignDownloadError("manifest selects a foreign or unexpected artifact path")
            if ref["sha256"] in seen:
                raise CampaignDownloadError("duplicate publication artifact")
            seen.add(ref["sha256"])
            total += ref["bytes"]
            planned.append((item["path_in_repo"], ref, kind))
        if total > publication.MAX_UPLOAD_BYTES:
            raise CampaignDownloadError("manifest exceeds total download byte bound")
        anchor = publication.sparse.artifact_ref(manifest.get("anchor_checkpoint"))
        if anchor["bytes"] > MAX_ANCHOR_BYTES:
            raise CampaignDownloadError("anchor exceeds download byte bound")
        reference_depth = 1
        if anchor_reference is not None:
            reference_depth = _reference_plan(anchor_reference, expected_artifact=anchor,
                                               seen=chain, depth=len(chain)) - len(_ancestor_manifests)
        elif local_anchor_resolver is None:
            raise CampaignDownloadError("explicit remote seed or verified local anchor is required")
        retained_anchor = local_anchor_resolver(anchor) if local_anchor_resolver is not None else None
        if retained_anchor is not None:
            retained_anchor = Path(retained_anchor).absolute()
            # A corrupt supplied parent is a local integrity failure, not a
            # reason to hide the failure behind a fresh remote download.
            publication._read(retained_anchor, MAX_ANCHOR_BYTES, anchor)
        elif anchor_reference is None:
            raise CampaignDownloadError("local resolver has no anchor and no remote reference was supplied")
        for remote, ref, kind in planned:
            fetch(remote, root / "artifacts" / ref["sha256"], ref["bytes"], ref=ref,
                  weight=kind.startswith("sparse_"))
        bundle = publication.load_sparse_update(local_manifest)
        ancestor_result = None
        if retained_anchor is not None:
            anchor_path = retained_anchor
        elif anchor_reference is not None:
            if anchor_reference.get("kind", "anchor") == "sparse":
                ancestor_result = resolve_campaign_anchor(anchor_reference,
                    root / "ancestors" / anchor_reference["sha256"], expected_artifact=anchor,
                    api=api, client=client, _ancestor_manifests=chain,
                    _local_anchor_resolver=local_anchor_resolver)
                anchor_path = Path(ancestor_result["materialized_checkpoint_path"])
                publication._read(anchor_path, MAX_ANCHOR_BYTES, anchor)
                for key in telemetry:
                    telemetry[key] += ancestor_result[key]
            else:
                anchor_path = root / "anchors" / (anchor["sha256"] + ".state.json")
                fetch(anchor_reference["path_in_repo"], anchor_path, anchor["bytes"], ref=anchor,
                      revision=anchor_reference["commit_sha"], weight=True)

        def resolve(ref):
            if ref == anchor:
                return anchor_path
            if ref["sha256"] not in bundle["by_sha"]:
                raise CampaignDownloadError("sparse replay selected an unpublished dependency")
            return root / "artifacts" / ref["sha256"]

        resolved = publication.sparse.resolve_checkpoint(manifest["checkpoint_artifact"], resolver=resolve)
        materialized = dict(resolved.materialized_checkpoint)
        if materialized != manifest["materialized_checkpoint"]:
            raise CampaignDownloadError("replayed bytes differ from published materialized identity")
        materialized_path = root / "materialized" / (materialized["sha256"] + ".state.json")
        materialized_raw = publication.sparse.canonical_checkpoint_bytes(resolved.state)
        if publication._ref(materialized_raw) != materialized:
            raise CampaignDownloadError("canonical replay identity differs")
        publication._write(materialized_path, materialized_raw)
        result = {"schema": DOWNLOAD_SCHEMA, "repository_id": repository_id, "commit_sha": commit_sha,
                  "path_in_repo": manifest_path, "manifest_path": str(local_manifest),
                  "local_manifest_path": str(local_manifest), "manifest_artifact": publication._ref(raw),
                  "candidate_version_id": manifest["version"]["version_id"],
                  "candidate_artifact": manifest["checkpoint_artifact"], "anchor_checkpoint": anchor,
                  "anchor_path": str(anchor_path), "materialized_checkpoint": materialized,
                  "materialized_checkpoint_artifact": materialized,
                  "materialized_checkpoint_path": str(materialized_path),
                  "state_identity": resolved.state_identity, "sparse_depth": resolved.depth,
                  "campaign_reference_depth": reference_depth,
                  "local_anchor_reused": retained_anchor is not None,
                  "ancestor_replay": ({key: ancestor_result[key] for key in
                      ("manifest_artifact", "materialized_checkpoint", "campaign_reference_depth", "replayed", "local_anchor_reused")}
                      if ancestor_result else None),
                  "replayed": True, "weights_downloaded": telemetry["downloaded_weight_files"] > 0,
                  "locally_qualified": False, "registration_performed": False,
                  "promotion_performed": False, "admitted": False, "formalized": False, **telemetry}
        publication._write(root / "receipts" / (publication._sha(publication._json(result)) + ".json"), publication._json(result))
        return result
