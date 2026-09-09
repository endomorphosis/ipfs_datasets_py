"""Fail-closed PCPR-055 Datasets signed tags and artifacts.

Produce a declared signed-tag policy and a declared artifact checksum
manifest for ipfs_datasets_py. The core install_requires set is empty;
that empty set is the signed-release profile, not an omission. Live
GPG/SSH git-tag signatures, cosign or minisign artifact signatures, and
published wheel/sdist/container identities stay typed unavailable.
Signatures and hashes are never invented.

This module is not release authority: it does not write DuckDB or Quack
state, does not create or push git tags, and never emits a closed PCPR
release outcome. Live claims require live evidence. Simulated results
are not live.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.assurance.dependency_locks import (
    CLOSED_RELEASE_OUTCOMES,
    DEVELOPMENT_REQUIREMENTS,
    PACKAGE_NAME,
    PACKAGE_VERSION,
    SEALED_PATH,
    SEALED_PYTHON,
    content_identity,
    discover_datasets_root,
    observe_sealed_validation_environment,
    pretty_json,
    render_release_lock,
    scan_requirement_text,
    sha256_bytes,
    typed_unavailable,
)
from ipfs_datasets_py.assurance.sbom_and_provenance import (
    render_build_provenance,
    render_declared_sbom,
)

INTERFACE: Final = "DatasetsSignedTagsAndArtifacts@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/signed-tags-and-artifacts@1"
TAG_POLICY_SCHEMA: Final = "ipfs_datasets_py/assurance/declared-signed-tag-policy@1"
CHECKSUM_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/declared-artifact-checksums@1"
)
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/signed-tags-and-artifacts-verdict@1"
)
PCPR_055_TASK_ID: Final = "PCPR-055"
PCPR_055_GOAL_ID: Final = "PCPR-G600"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
EVIDENCE_ID: Final = "pcpr/datasets-signed-tags-and-artifacts@1"

CANONICAL_PYTHON_REQUIRES: Final = ">=3.12"
SOURCE_REPOSITORY: Final = "endomorphosis/ipfs_datasets_py"
SOURCE_ORIGIN_URL: Final = "https://github.com/endomorphosis/ipfs_datasets_py"
TAG_KIND: Final = "declared_signed_tag_policy"
CHECKSUM_KIND: Final = "declared_artifact_checksum_manifest"
INTENDED_TAG_NAME: Final = f"{PACKAGE_NAME}-v{PACKAGE_VERSION}"
INTENDED_TAG_TYPE: Final = "annotated"
CHECKSUM_ALGORITHM: Final = "sha256"
SIGNED_DIR_RELPATH: Final = "packaging/pcpr/signed/cpython312"
TAG_POLICY_JSON_NAME: Final = "release.tag-policy.json"
CHECKSUMS_JSON_NAME: Final = "release.checksums.json"
SHA256SUMS_NAME: Final = "SHA256SUMS"
SIGNED_README_RELPATH: Final = "packaging/pcpr/signed/README.md"
LOCK_RELPATH: Final = "packaging/pcpr/locks/cpython312/release.lock.json"
LOCK_TXT_RELPATH: Final = "packaging/pcpr/locks/cpython312/release.txt"
SBOM_RELPATH: Final = "packaging/pcpr/sbom/cpython312/release.sbom.json"
PROVENANCE_RELPATH: Final = (
    "packaging/pcpr/provenance/cpython312/release.provenance.json"
)
SOURCE_DATE_EPOCH: Final = "0"

EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "measured",
        "measured_live",
        "measured_hermetic",
        "estimated",
        "simulated",
        "unavailable",
    }
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_055_signed_tags_and_artifacts.py",
)

SIGNING_TOOLS: Final[tuple[str, ...]] = (
    "gpg",
    "gpg2",
    "gpgsm",
    "ssh-keygen",
    "cosign",
    "minisign",
    "signify",
    "signify-openbsd",
    "slsa-generator",
    "in-toto-sign",
)

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "tag_policy_files_match_generator",
        "checksum_files_match_generator",
        "pyproject_signed_tags_and_artifacts_table",
        "hashes_not_invented",
        "signatures_not_invented",
        "no_mutable_main_reference",
        "tag_kind_is_declared_signed_tag_policy",
        "checksum_kind_is_declared_artifact_checksum_manifest",
        "core_release_profile_is_empty",
        "development_requirements_are_not_signed_release",
        "manifest_advertises_signed_tags_and_artifacts",
        "lock_sbom_provenance_checksums_measured",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "hashes_invented",
        "signatures_invented",
        "mutable_main_reference",
        "simulated_results_represented_as_live",
        "signed_tag_represented_as_live",
        "gpg_signature_represented_as_live",
        "cosign_signature_represented_as_live",
        "closed_release_represented_as_live",
        "wheel_represented_as_live_release",
        "published_tag_represented_as_live",
    }
)

SIGNED_README: Final = """# PCPR-055 declared signed tags and artifacts

These files are the Datasets *release* signed-tag policy and artifact
checksum manifest. The core `setup.py` install_requires set is empty;
that empty set is the signed-release profile, not an omission. They are
not a live GPG/SSH git tag, not a cosign signature, not a published
wheel or sdist, and not a closed PCPR release.

- `cpython312/release.tag-policy.json` is the canonical declared tag
  policy. The intended annotated tag name is `ipfs_datasets_py-v0.2.0`.
  Exact commit and tree are bound by the PCPR-055 receipt
  `current_tree_binding` because nested admission rewrites HEAD.
  `origin/main` is not the release identity.
- `cpython312/release.checksums.json` and `cpython312/SHA256SUMS` checksum
  the committed PCPR-053 lock and PCPR-054 SBOM/provenance files. Wheel,
  sdist, container, and signature identities stay typed unavailable.
  Hashes and signatures are never invented.
- Development `requirements.txt` VCS pins remain source-checkout
  development only and are not this signed release.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
"""


class SignedTagsError(Exception):
    """Fail-closed PCPR-055 contract error."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SignedTagsError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise SignedTagsError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise SignedTagsError(f"{name} must not be a closed PCPR release outcome")


def _which_sealed(name: str) -> str:
    path = shutil.which(name, path=SEALED_PATH)
    if not path:
        return "unavailable"
    resolved = Path(path)
    if not resolved.is_file():
        return "unavailable"
    return str(resolved)


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def observe_signing_tooling() -> dict[str, Any]:
    env = observe_sealed_validation_environment()
    tools = {name.replace("-", "_"): _which_sealed(name) for name in SIGNING_TOOLS}
    return {
        **env,
        "signing_tools": tools,
        "any_live_tag_signer": False,
        "any_live_artifact_signer": False,
        "evidence_kind": "measured",
    }


def parse_pyproject_signed_table(text: str) -> dict[str, Any]:
    import tomllib

    table = tomllib.loads(_text(text, "pyproject.toml"))
    if not isinstance(table, dict):
        raise SignedTagsError("pyproject.toml must be a table")
    tool = table.get("tool")
    payload: dict[str, Any] = {}
    if isinstance(tool, dict):
        datasets = tool.get("ipfs-datasets-py")
        if isinstance(datasets, dict):
            raw = datasets.get("signed-tags-and-artifacts")
            if isinstance(raw, dict):
                payload = dict(raw)
    return payload


@dataclass(frozen=True)
class OutcomeProbe:
    probe_id: str
    present: bool | None
    evidence_kind: str
    live: bool
    simulated_represented_as_live: bool
    reason: str
    details: Mapping[str, Any] = MappingProxyType({})

    def to_mapping(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "present": self.present,
            "evidence_kind": self.evidence_kind,
            "live": self.live,
            "simulated_represented_as_live": self.simulated_represented_as_live,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SignedTagsVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    sibling_source_required: bool
    hashes_invented: bool
    signatures_invented: bool
    live_signed_tag: bool
    live_signed_tag_evidence_kind: str
    live_artifact_signature: bool
    live_artifact_signature_evidence_kind: str
    mutable_main_reference: bool
    simulated_results_represented_as_live: bool
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str
    tag_policy_cid: str
    checksums_cid: str
    sbom_cid: str
    provenance_cid: str
    lock_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "tag_policy_cid": self.tag_policy_cid,
            "checksums_cid": self.checksums_cid,
            "sbom_cid": self.sbom_cid,
            "provenance_cid": self.provenance_cid,
            "lock_cid": self.lock_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "sibling_source_required": self.sibling_source_required,
            "hashes_invented": self.hashes_invented,
            "signatures_invented": self.signatures_invented,
            "live_signed_tag": self.live_signed_tag,
            "live_signed_tag_evidence_kind": self.live_signed_tag_evidence_kind,
            "live_artifact_signature": self.live_artifact_signature,
            "live_artifact_signature_evidence_kind": (
                self.live_artifact_signature_evidence_kind
            ),
            "mutable_main_reference": self.mutable_main_reference,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def _probe(
    probe_id: str,
    present: bool | None,
    *,
    reason: str,
    evidence_kind: str = "measured",
    live: bool = False,
    details: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind=evidence_kind,
        live=live,
        simulated_represented_as_live=False,
        reason=reason,
        details=MappingProxyType(dict(details or {})),
    )


def _file_checksum(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        return {
            "path": relative,
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "live": False,
            "sha256": "unavailable",
            "bytes": None,
            "reason": f"{relative} is not present in this checkout.",
        }
    data = path.read_bytes()
    return {
        "path": relative,
        "status": "observed",
        "evidence_kind": "measured",
        "live": False,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "reason": "SHA-256 of committed bytes. This is not a published release digest.",
    }


def render_declared_tag_policy(root: Path | None = None) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise SignedTagsError("Datasets package root was not found")
    lock = render_release_lock(package_root)
    sbom = render_declared_sbom(package_root)
    provenance = render_build_provenance(package_root, sbom=sbom)
    tooling = observe_signing_tooling()
    intended_sign = (
        f"PATH={SEALED_PATH} git -c tag.gpgSign=true tag -s "
        f"{INTENDED_TAG_NAME} -m "
        f"'PCPR declared annotated tag for {PACKAGE_NAME} {PACKAGE_VERSION}'"
    )
    document = {
        "schema": TAG_POLICY_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_055_TASK_ID,
        "goal_id": PCPR_055_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "python_requires": CANONICAL_PYTHON_REQUIRES,
        "tag_kind": TAG_KIND,
        "intended_tag_name": INTENDED_TAG_NAME,
        "intended_tag_type": INTENDED_TAG_TYPE,
        "lock_cid": lock["lock_cid"],
        "sbom_cid": sbom["sbom_cid"],
        "provenance_cid": provenance["provenance_cid"],
        "source": {
            "kind": "git",
            "repository": SOURCE_REPOSITORY,
            "origin_url": SOURCE_ORIGIN_URL,
            "binding": "current_head_not_mutable_main",
            "mutable_main_reference": False,
            "commit": {
                "status": "observed_at_evaluation",
                "evidence_kind": "measured",
                "live": False,
                "field": "PCPR-055 receipt current_tree_binding",
                "reason": (
                    "Exact commit and tree are bound by the task receipt "
                    "because nested admission rewrites HEAD. This document "
                    "does not pin origin/main."
                ),
            },
        },
        "signing": {
            "status": "unavailable",
            "evidence_kind": "unavailable",
            "live": False,
            "signed": False,
            "algorithm": "git-gpg-or-ssh",
            "key_id": "unavailable",
            "signature": "unavailable",
            "invented": False,
            "reason": (
                "gpg, ssh signing keys, and cosign are not admitted live "
                "signers in the sealed environment. A signature was not "
                "invented and a git tag was not created or pushed."
            ),
            "tools": dict(tooling["signing_tools"]),
        },
        "commands": {
            "materialize": (
                'python -c "from ipfs_datasets_py.assurance.'
                "signed_tags_and_artifacts import "
                'write_signed_tags_and_artifacts_files; '
                'write_signed_tags_and_artifacts_files()"'
            ),
            "intended_signed_tag": intended_sign,
            "observed_signed_tag": "unavailable",
            "git_tag_created": False,
            "git_tag_pushed": False,
        },
        "protection": typed_unavailable(
            reason=(
                "Protected signed tags and branch protection are PCPR-057. "
                "This task does not claim GitHub tag protection."
            )
        ),
        "live": False,
        "published": False,
        "release_claim": False,
        "closed_release_outcome": None,
        "hashes_invented": False,
        "signatures_invented": False,
        "sibling_source_required": False,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "evidence_kind": "measured",
    }
    document["tag_policy_cid"] = content_identity(
        {key: value for key, value in document.items() if key != "tag_policy_cid"}
    )
    return document


def render_declared_checksums(
    root: Path | None = None,
    *,
    tag_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    package_root = root or discover_datasets_root()
    if package_root is None:
        raise SignedTagsError("Datasets package root was not found")
    policy = dict(tag_policy or render_declared_tag_policy(package_root))
    measured = [
        _file_checksum(package_root, LOCK_RELPATH),
        _file_checksum(package_root, LOCK_TXT_RELPATH),
        _file_checksum(package_root, SBOM_RELPATH),
        _file_checksum(package_root, PROVENANCE_RELPATH),
    ]
    document = {
        "schema": CHECKSUM_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_055_TASK_ID,
        "goal_id": PCPR_055_GOAL_ID,
        "program_id": PCPR_PROGRAM_ID,
        "package_name": PACKAGE_NAME,
        "package_version": PACKAGE_VERSION,
        "checksum_kind": CHECKSUM_KIND,
        "algorithm": CHECKSUM_ALGORITHM,
        "tag_policy_cid": policy["tag_policy_cid"],
        "lock_cid": policy["lock_cid"],
        "sbom_cid": policy["sbom_cid"],
        "provenance_cid": policy["provenance_cid"],
        "measured_files": measured,
        "artifacts": {
            "lock": measured[0],
            "lock_txt": measured[1],
            "sbom": measured[2],
            "provenance": measured[3],
            "wheel": typed_unavailable(
                reason=(
                    "No published wheel digest is bound. Hermetic private "
                    "builds are not a PCPR release. A wheel hash was not "
                    "invented."
                )
            ),
            "sdist": typed_unavailable(
                reason=(
                    "No published sdist digest is bound. Hermetic private "
                    "builds are not a PCPR release. An sdist hash was not "
                    "invented."
                )
            ),
            "container": typed_unavailable(
                reason="No container digest is bound. A digest was not invented."
            ),
            "signed_tag": typed_unavailable(
                reason=(
                    "No live signed git tag exists for this declared policy. "
                    "A tag signature was not invented."
                )
            ),
            "detached_signature": typed_unavailable(
                reason=(
                    "cosign, minisign, and in-toto are not admitted live "
                    "signers. A detached signature was not invented."
                )
            ),
        },
        "hashes_invented": False,
        "signatures_invented": False,
        "live": False,
        "published": False,
        "release_claim": False,
        "closed_release_outcome": None,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "evidence_kind": "measured",
    }
    document["checksums_cid"] = content_identity(
        {key: value for key, value in document.items() if key != "checksums_cid"}
    )
    return document


def render_sha256sums(checksums: Mapping[str, Any]) -> str:
    lines = [
        "# PCPR-055 declared artifact checksums.",
        "# Wheel, sdist, container, and signature identities stay typed unavailable.",
        "# Hashes were not invented. This is not a live signed release.",
    ]
    files = checksums.get("measured_files") or []
    if not isinstance(files, list):
        raise SignedTagsError("measured_files must be a list")
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "observed":
            continue
        digest = item.get("sha256")
        path = item.get("path")
        if not isinstance(digest, str) or not isinstance(path, str):
            raise SignedTagsError("measured checksum entry is malformed")
        if digest in {"", "unavailable"}:
            raise SignedTagsError("measured checksum hash must not be invented or empty")
        lines.append(f"{digest}  {path}")
    return "\n".join(lines) + "\n"


def artifact_paths(root: Path) -> dict[str, Path]:
    return {
        "tag_policy": root / SIGNED_DIR_RELPATH / TAG_POLICY_JSON_NAME,
        "checksums": root / SIGNED_DIR_RELPATH / CHECKSUMS_JSON_NAME,
        "sha256sums": root / SIGNED_DIR_RELPATH / SHA256SUMS_NAME,
        "readme": root / SIGNED_README_RELPATH,
    }


def write_signed_tags_and_artifacts_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise SignedTagsError("Datasets package root was not found")
    tag_policy = render_declared_tag_policy(root)
    checksums = render_declared_checksums(root, tag_policy=tag_policy)
    paths = artifact_paths(root)
    _atomic_write(paths["tag_policy"], pretty_json(tag_policy))
    _atomic_write(paths["checksums"], pretty_json(checksums))
    _atomic_write(paths["sha256sums"], render_sha256sums(checksums))
    readme = SIGNED_README if SIGNED_README.endswith("\n") else SIGNED_README + "\n"
    _atomic_write(paths["readme"], readme)
    return {
        "tag_policy": tag_policy,
        "checksums": checksums,
        "paths": {name: str(path) for name, path in paths.items()},
    }


def verify_signed_tags_and_artifacts_files(
    start: Path | None = None,
) -> dict[str, Any]:
    root = discover_datasets_root(start)
    if root is None:
        raise SignedTagsError("Datasets package root was not found")
    tag_policy = render_declared_tag_policy(root)
    checksums = render_declared_checksums(root, tag_policy=tag_policy)
    paths = artifact_paths(root)
    missing: list[str] = []
    tag_ok = False
    checksums_ok = False
    sha256sums_ok = False
    readme_ok = False
    expected_readme = (
        SIGNED_README if SIGNED_README.endswith("\n") else SIGNED_README + "\n"
    )
    expected_sums = render_sha256sums(checksums)
    for name, path in paths.items():
        if not path.is_file():
            missing.append(name)
            continue
        if name == "tag_policy":
            tag_ok = json.loads(path.read_text(encoding="utf-8")) == tag_policy
        elif name == "checksums":
            checksums_ok = json.loads(path.read_text(encoding="utf-8")) == checksums
        elif name == "sha256sums":
            sha256sums_ok = path.read_text(encoding="utf-8") == expected_sums
        elif name == "readme":
            readme_ok = path.read_text(encoding="utf-8") == expected_readme
    return {
        "ok": not missing and tag_ok and checksums_ok and sha256sums_ok and readme_ok,
        "missing": missing,
        "tag_policy_ok": tag_ok,
        "checksums_ok": checksums_ok,
        "sha256sums_ok": sha256sums_ok,
        "readme_ok": readme_ok,
        "tag_policy_cid": tag_policy["tag_policy_cid"],
        "checksums_cid": checksums["checksums_cid"],
        "lock_cid": tag_policy["lock_cid"],
        "sbom_cid": tag_policy["sbom_cid"],
        "provenance_cid": tag_policy["provenance_cid"],
    }


def current_head_static_probes(
    start: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    root = discover_datasets_root(start)
    if root is None:
        raise SignedTagsError("Datasets package root was not found")
    lock = render_release_lock(root)
    tag_policy = render_declared_tag_policy(root)
    checksums = render_declared_checksums(root, tag_policy=tag_policy)
    verified = verify_signed_tags_and_artifacts_files(root)
    table = parse_pyproject_signed_table(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )
    tooling = observe_signing_tooling()
    development = (root / DEVELOPMENT_REQUIREMENTS).read_text(encoding="utf-8")
    development_scan = scan_requirement_text(development)
    by_path = {item.get("path"): item for item in checksums["measured_files"]}
    measured_ok = all(
        by_path.get(path, {}).get("status") == "observed"
        for path in (LOCK_TXT_RELPATH, SBOM_RELPATH, PROVENANCE_RELPATH)
    )
    mutable_main = bool(tag_policy["source"]["mutable_main_reference"])
    manifest_ok = False
    manifest_reason = (
        "LogicPlatformManifest does not advertise DatasetsSignedTagsAndArtifacts@1"
    )
    try:
        from ipfs_datasets_py.logic.platform.manifest import (
            DEFAULT_LOGIC_PLATFORM_MANIFEST,
        )

        versions = DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions
        roots = DEFAULT_LOGIC_PLATFORM_MANIFEST.schema_roots
        operations = DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions
        manifest_ok = (
            versions.get(INTERFACE) == "1"
            and roots.get("datasets_signed_tags_and_artifacts") == SCHEMA
            and operations.get("signed_tags_and_artifacts") == "1"
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_sibling_repos() is False
            and DEFAULT_LOGIC_PLATFORM_MANIFEST.requires_repository_layout()
            is False
        )
        if manifest_ok:
            manifest_reason = (
                "LogicPlatformManifest advertises DatasetsSignedTagsAndArtifacts@1 "
                "and does not require sibling repositories."
            )
    except Exception as exc:  # pragma: no cover - import/shape failure is a probe
        manifest_reason = str(exc)
    probes = [
        _probe(
            "tag_policy_files_match_generator",
            verified.get("ok") is True and verified.get("tag_policy_ok") is True,
            reason=(
                "Committed signed-tag policy matches the generator."
                if verified.get("tag_policy_ok") is True
                else "Committed signed-tag policy is missing or drifts."
            ),
            details=verified,
        ),
        _probe(
            "checksum_files_match_generator",
            verified.get("ok") is True
            and verified.get("checksums_ok") is True
            and verified.get("sha256sums_ok") is True,
            reason=(
                "Committed checksum manifest and SHA256SUMS match the generator."
                if verified.get("checksums_ok") is True
                else "Committed checksum files are missing or drift."
            ),
        ),
        _probe(
            "pyproject_signed_tags_and_artifacts_table",
            table.get("interface") == INTERFACE
            and table.get("schema") == SCHEMA
            and table.get("task-id") == PCPR_055_TASK_ID
            and table.get("tag-kind") == TAG_KIND,
            reason=(
                "pyproject.toml declares DatasetsSignedTagsAndArtifacts@1."
                if table.get("interface") == INTERFACE
                else "pyproject.toml does not declare DatasetsSignedTagsAndArtifacts@1."
            ),
            details={"table": table},
        ),
        _probe(
            "hashes_not_invented",
            tag_policy["hashes_invented"] is False
            and checksums["hashes_invented"] is False,
            reason="Hashes were not invented; unpublished artifact hashes stay typed unavailable.",
        ),
        _probe(
            "hashes_invented",
            False,
            reason="Hashes must not be invented for unavailable wheel/sdist identities.",
        ),
        _probe(
            "signatures_not_invented",
            tag_policy["signatures_invented"] is False
            and checksums["signatures_invented"] is False,
            reason="Signatures were not invented; live signing stays typed unavailable.",
        ),
        _probe(
            "signatures_invented",
            False,
            reason="A signature must not be invented for an unavailable signer.",
        ),
        _probe(
            "no_mutable_main_reference",
            mutable_main is False,
            reason="Signed-tag policy does not pin origin/main as the release identity.",
        ),
        _probe(
            "mutable_main_reference",
            mutable_main,
            reason="Mutable main must not be the release identity.",
        ),
        _probe(
            "tag_kind_is_declared_signed_tag_policy",
            tag_policy["tag_kind"] == TAG_KIND,
            reason="Tag kind is declared_signed_tag_policy, not a live signed git tag.",
        ),
        _probe(
            "checksum_kind_is_declared_artifact_checksum_manifest",
            checksums["checksum_kind"] == CHECKSUM_KIND,
            reason="Checksum kind is declared_artifact_checksum_manifest, not a live signed artifact.",
        ),
        _probe(
            "core_release_profile_is_empty",
            lock["direct_requirement_count"] == 0,
            reason="Datasets core install_requires is empty; that empty set is the signed-release profile.",
        ),
        _probe(
            "development_requirements_are_not_signed_release",
            True,
            reason=(
                "requirements.txt may carry source-checkout Git pins; it is "
                "not the signed release."
            ),
            details={"development_vcs": list(development_scan["vcs"])},
        ),
        _probe(
            "manifest_advertises_signed_tags_and_artifacts",
            manifest_ok,
            reason=manifest_reason,
        ),
        _probe(
            "lock_sbom_provenance_checksums_measured",
            measured_ok,
            reason="Committed lock, SBOM, and provenance bytes were checksummed; hashes were not invented.",
            details={"measured_files": checksums["measured_files"]},
        ),
        _probe(
            "simulated_results_represented_as_live",
            False,
            reason="Simulated results are not represented as live.",
        ),
        _probe(
            "signed_tag_represented_as_live",
            False,
            reason="No git tag signature is represented as live.",
        ),
        _probe(
            "gpg_signature_represented_as_live",
            False,
            reason="No GPG signature is represented as live.",
        ),
        _probe(
            "cosign_signature_represented_as_live",
            False,
            reason="No cosign signature is represented as live.",
        ),
        _probe(
            "closed_release_represented_as_live",
            False,
            reason="This task does not publish a PCPR release.",
        ),
        _probe(
            "wheel_represented_as_live_release",
            False,
            reason="No wheel digest is represented as a live published release.",
        ),
        _probe(
            "published_tag_represented_as_live",
            False,
            reason="No git tag was created or pushed.",
        ),
        _probe(
            "live_signed_tag",
            None,
            evidence_kind="unavailable",
            reason=(
                "gpg/SSH signing keys and a verified annotated tag for "
                f"{INTENDED_TAG_NAME} are absent. A signed tag was not invented."
            ),
            details={"tools": tooling.get("signing_tools")},
        ),
        _probe(
            "live_artifact_signature",
            None,
            evidence_kind="unavailable",
            reason=(
                "cosign, minisign, and in-toto are absent as admitted live "
                "signers. A signed artifact was not invented."
            ),
            details={"tools": tooling.get("signing_tools")},
        ),
    ]
    return tuple(probes)


def qualify_signed_tags_and_artifacts(
    probes: Sequence[OutcomeProbe],
    *,
    tag_policy_cid: str,
    checksums_cid: str,
    sbom_cid: str,
    provenance_cid: str,
    lock_cid: str,
) -> SignedTagsVerdict:
    if not probes:
        raise SignedTagsError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise SignedTagsError("live claims require measured_live evidence")
        if probe.simulated_represented_as_live:
            raise SignedTagsError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)

    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    mutable = next(
        (
            item.present is True
            for item in normalized
            if item.probe_id == "mutable_main_reference"
        ),
        False,
    )
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_055_TASK_ID,
        "goal_id": PCPR_055_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "sibling_source_required": False,
        "hashes_invented": False,
        "signatures_invented": False,
        "live_signed_tag": False,
        "live_signed_tag_evidence_kind": "unavailable",
        "live_artifact_signature": False,
        "live_artifact_signature_evidence_kind": "unavailable",
        "mutable_main_reference": mutable,
        "simulated_results_represented_as_live": False,
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
        "tag_policy_cid": tag_policy_cid,
        "checksums_cid": checksums_cid,
        "sbom_cid": sbom_cid,
        "provenance_cid": provenance_cid,
        "lock_cid": lock_cid,
    }
    return SignedTagsVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        sibling_source_required=False,
        hashes_invented=False,
        signatures_invented=False,
        live_signed_tag=False,
        live_signed_tag_evidence_kind="unavailable",
        live_artifact_signature=False,
        live_artifact_signature_evidence_kind="unavailable",
        mutable_main_reference=mutable,
        simulated_results_represented_as_live=False,
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
        tag_policy_cid=tag_policy_cid,
        checksums_cid=checksums_cid,
        sbom_cid=sbom_cid,
        provenance_cid=provenance_cid,
        lock_cid=lock_cid,
    )


def qualify_current_head_signed_tags_and_artifacts(
    start: Path | None = None,
) -> SignedTagsVerdict:
    root = discover_datasets_root(start)
    tag_policy = render_declared_tag_policy(root)
    checksums = render_declared_checksums(root, tag_policy=tag_policy)
    return qualify_signed_tags_and_artifacts(
        current_head_static_probes(start),
        tag_policy_cid=str(tag_policy["tag_policy_cid"]),
        checksums_cid=str(checksums["checksums_cid"]),
        sbom_cid=str(tag_policy["sbom_cid"]),
        provenance_cid=str(tag_policy["provenance_cid"]),
        lock_cid=str(tag_policy["lock_cid"]),
    )


def pcpr_055_receipt_promotion(
    verdict: SignedTagsVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise SignedTagsError(
            "signed tags and artifacts must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise SignedTagsError("signed tags and artifacts must not claim a PCPR release")
    if verdict.completion_authoritative:
        raise SignedTagsError("signed-tags-and-artifacts completion is not authoritative")
    if verdict.duckdb_or_quack_state_written:
        raise SignedTagsError(
            "signed tags and artifacts must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise SignedTagsError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeeraa5xlx4m2q6ja265baz3izeulelopvp7u6lhfrjzreihccldbshsa"
)


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "INTENDED_TAG_NAME",
    "OutcomeProbe",
    "PCPR_055_GOAL_ID",
    "PCPR_055_TASK_ID",
    "CHECKSUM_KIND",
    "TAG_KIND",
    "SCHEMA",
    "SEALED_PATH",
    "SEALED_PYTHON",
    "SignedTagsError",
    "SignedTagsVerdict",
    "current_head_static_probes",
    "pcpr_055_receipt_promotion",
    "qualify_current_head_signed_tags_and_artifacts",
    "qualify_signed_tags_and_artifacts",
    "render_declared_checksums",
    "render_declared_tag_policy",
    "verify_signed_tags_and_artifacts_files",
    "write_signed_tags_and_artifacts_files",
]
