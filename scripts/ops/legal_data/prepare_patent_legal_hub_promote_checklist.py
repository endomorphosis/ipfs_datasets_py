#!/usr/bin/env python3
"""Build an exact-digest operator promote checklist for Hub index publication (PATLAW-178).

Checklist-only surface for corpus / BM25 / vector / knowledge-graph Hub index
packages that have already been packaged (PATLAW-174), admitted (PATLAW-175),
staged (PATLAW-176), and optionally pin-verified (PATLAW-177).

This tool:

* binds ``package_root_cid``, ``plan_digest``, ``staged_diff_digest``,
  per-projection digests, and staged commit SHAs into a content-free checklist;
* enumerates natural-person steps (approve → promote → pin → canary → rollback);
* never promotes, merges, pins, canaries, or contacts the live Hub;
* never introduces an auto-promote path;
* rejects unpinned revision tokens (``main`` / ``latest`` / ``HEAD``);
* refuses credential-shaped material in inputs or outputs.

Default mode is dry preparation only. Write the checklist with ``--output``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (  # noqa: E402
    CredentialLeakError,
    reject_credentials_in_payload,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (  # noqa: E402
    INDEX_FAMILIES,
    canonical_json,
)


TASK_ID = "PATLAW-178"
GOAL_ID = "PATLAW-G213"
PROGRAM_ID = "patent-legal-intelligence-v1"
PRODUCER = "prepare_patent_legal_hub_promote_checklist.py"
CHECKLIST_SCHEMA = "patent-legal-hub-index-promote-checklist/v1"
CODE_VERSION = "1"

PROJECTION_FAMILIES: tuple[str, ...] = (
    "corpus",
    "bm25",
    "vectors",
    "knowledge_graph",
)

# Unpinned / floating revision tokens that must never be treated as promote targets.
_UNPINNED_REVISION_TOKENS = frozenset(
    {
        "main",
        "master",
        "latest",
        "head",
        "origin/main",
        "origin/master",
        "refs/heads/main",
        "refs/heads/master",
    }
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_CID_RE = re.compile(r"^(?:bafy|bagu|Qm)[a-zA-Z0-9]+$")

# Keys allowed in the content-free checklist root (and common nested leaves).
_CONTENT_FREE_KEY_ALLOWLIST = frozenset(
    {
        "acceptance",
        "actions",
        "action_id",
        "action_ids",
        "all_steps_not_automated",
        "all_steps_require_human",
        "artifact_digest",
        "artifact_digests",
        "artifact_path",
        "artifacts",
        "auto_promote",
        "automated_by_this_tool",
        "base_commit",
        "base_revisions",
        "binds",
        "binds_artifact_digests",
        "binds_staged_commit_sha",
        "blockers",
        "bm25",
        "branch_name",
        "checklist_digest_sha256",
        "checklist_schema",
        "code_version",
        "commit_sha",
        "corpus",
        "dataset_id",
        "description",
        "digest",
        "disposition",
        "documents_natural_person_actions",
        "evidence",
        "evidence_gaps",
        "family",
        "generated_at",
        "goal_id",
        "graph",
        "human_approval_required",
        "index_families",
        "kind",
        "knowledge_graph",
        "label",
        "live_network",
        "main_published",
        "mode",
        "no_auto_promote_path",
        "notes",
        "operator_checklist",
        "organization",
        "package_digest_sha256",
        "package_root_cid",
        "path",
        "plan_digest",
        "pointers_moved",
        "pointers_moved_by_checklist",
        "producer",
        "program_id",
        "projection",
        "projection_digests",
        "projections",
        "promoted_commit_sha",
        "pull_request_number",
        "reason",
        "receipt_path",
        "receipt_schema",
        "release_id",
        "release_root_cid",
        "requires_human",
        "root_cid",
        "schema_version",
        "sha256",
        "size_bytes",
        "source",
        "source_receipt",
        "stage_receipt",
        "stage_status",
        "staged_commit_sha",
        "staged_diff_digest",
        "staged_repositories",
        "status",
        "step",
        "step_id",
        "steps",
        "task_id",
        "title",
        "tokens_used",
        "unpinned_revision_rejected",
        "vector",
        "vectors",
        "verification_bound",
        "verification_prebound",
        "verification_receipt",
        "verification_status",
        "version_tag",
        "warning",
        "warnings",
    }
)


class PromoteChecklistError(RuntimeError):
    """Fail-closed error for promote checklist preparation."""

    code = "promote_checklist_error"


class UnpinnedRevisionError(PromoteChecklistError):
    code = "unpinned_revision_forbidden"


class EvidenceGapError(PromoteChecklistError):
    code = "evidence_gap"


class ContentFreeViolationError(PromoteChecklistError):
    code = "content_free_violation"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromoteChecklistError(f"cannot read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PromoteChecklistError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PromoteChecklistError(f"expected JSON object in {path}")
    data = dict(payload)
    try:
        reject_credentials_in_payload(data, label=str(path))
    except CredentialLeakError as exc:
        raise PromoteChecklistError(str(exc)) from exc
    return data


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _casefold(value: Any) -> str:
    return _text(value).casefold()


def _is_unpinned_revision(value: Any) -> bool:
    token = _casefold(value)
    if not token:
        return False
    if token in _UNPINNED_REVISION_TOKENS:
        return True
    # Bare HEAD variants (case-insensitive already via casefold).
    if token.endswith("/head") or token == "refs/heads/head":
        return True
    return False


def _reject_unpinned(value: Any, *, label: str) -> str:
    text = _text(value)
    if _is_unpinned_revision(text):
        raise UnpinnedRevisionError(
            f"{label} rejects unpinned revision token {text!r}; "
            "require an exact commit SHA or content digest"
        )
    return text


def _optional_digest(value: Any, *, label: str, require: bool = False) -> str:
    text = _reject_unpinned(value, label=label)
    if not text:
        if require:
            raise EvidenceGapError(f"missing required {label}")
        return ""
    lowered = text.casefold()
    if _HEX64_RE.fullmatch(lowered) or _HEX40_RE.fullmatch(lowered):
        return lowered
    if _CID_RE.fullmatch(text):
        return text
    # Accept opaque non-floating digests/CIDs that are not unpinned tokens.
    if any(ch.isspace() for ch in text):
        raise PromoteChecklistError(f"{label} must not contain whitespace")
    return text


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    body = canonical_json(dict(payload)).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _assert_content_free_keys(payload: Any, *, path: str = "checklist") -> None:
    if isinstance(payload, Mapping):
        for key, child in payload.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text not in _CONTENT_FREE_KEY_ALLOWLIST:
                raise ContentFreeViolationError(
                    f"non-allowlisted key in content-free checklist: {child_path}"
                )
            _assert_content_free_keys(child, path=child_path)
    elif isinstance(payload, (list, tuple)):
        for index, child in enumerate(payload):
            _assert_content_free_keys(child, path=f"{path}[{index}]")
    elif isinstance(payload, str):
        # Disallow multi-paragraph free text / narrative blobs.
        if len(payload) > 2000:
            raise ContentFreeViolationError(
                f"oversized string at {path} (content-free limit 2000 chars)"
            )
    elif payload is None or isinstance(payload, (bool, int, float)):
        return
    else:
        raise ContentFreeViolationError(
            f"unsupported value type at {path}: {type(payload).__name__}"
        )


def _extract_projection_digests(stage_receipt: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Collect per-projection digests from a stage / dry-run / verify receipt."""
    out: dict[str, dict[str, str]] = {
        family: {} for family in PROJECTION_FAMILIES
    }

    # Direct family root CIDs from dry-run / stage receipts.
    root_map = {
        "corpus": "corpus_root_cid",
        "bm25": "bm25_root_cid",
        "vectors": "vector_root_cid",
        "knowledge_graph": "graph_root_cid",
    }
    for family, key in root_map.items():
        val = _optional_digest(stage_receipt.get(key), label=key)
        if val:
            out[family]["root_cid"] = val

    # Nested projection_digests maps (verify receipts / enriched stage receipts).
    nested = stage_receipt.get("projection_digests") or stage_receipt.get(
        "projections"
    )
    if isinstance(nested, Mapping):
        for family, blob in nested.items():
            fam = _casefold(family)
            if fam in ("vector", "embedding", "embeddings"):
                fam = "vectors"
            if fam in ("graph", "kg", "knowledgegraph"):
                fam = "knowledge_graph"
            if fam not in out:
                continue
            if isinstance(blob, Mapping):
                for k, v in blob.items():
                    dig = _optional_digest(v, label=f"projection_digests.{fam}.{k}")
                    if dig:
                        out[fam][str(k)] = dig
            else:
                dig = _optional_digest(blob, label=f"projection_digests.{fam}")
                if dig:
                    out[fam]["digest"] = dig

    # Artifact inventory style lists.
    artifacts = stage_receipt.get("artifacts") or stage_receipt.get(
        "artifact_digests"
    )
    if isinstance(artifacts, Mapping):
        for family, blob in artifacts.items():
            fam = _casefold(family)
            if fam in ("vector", "embedding", "embeddings"):
                fam = "vectors"
            if fam in ("graph", "kg"):
                fam = "knowledge_graph"
            if fam not in out:
                continue
            if isinstance(blob, Mapping):
                for k, v in blob.items():
                    dig = _optional_digest(v, label=f"artifacts.{fam}.{k}")
                    if dig:
                        out[fam][str(k)] = dig

    # Drop empty families for cleaner gaps detection.
    return {k: v for k, v in out.items() if v}


def _extract_staged_repositories(
    stage_receipt: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw = stage_receipt.get("repositories") or stage_receipt.get(
        "staged_repositories"
    ) or ()
    repos: list[dict[str, Any]] = []
    if not isinstance(raw, (list, tuple)):
        return repos
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        dataset_id = _text(item.get("dataset_id"))
        staged_commit = _reject_unpinned(
            item.get("staged_commit_sha") or item.get("commit_sha"),
            label=f"repositories[{dataset_id}].staged_commit_sha",
        )
        base_commit = _reject_unpinned(
            item.get("base_commit") or item.get("base_revision"),
            label=f"repositories[{dataset_id}].base_commit",
        )
        branch = _text(item.get("branch_name") or item.get("branch"))
        if branch and _is_unpinned_revision(branch):
            # Stage branches named main/master are forbidden.
            raise UnpinnedRevisionError(
                f"stage branch must not be a default branch: {branch!r}"
            )
        entry: dict[str, Any] = {
            "dataset_id": dataset_id,
            "staged_commit_sha": staged_commit.casefold() if staged_commit else "",
            "base_commit": base_commit.casefold() if base_commit else "",
            "branch_name": branch,
        }
        prn = item.get("pull_request_number")
        if prn is not None and str(prn).strip() != "":
            entry["pull_request_number"] = int(prn)
        repos.append(entry)
    return repos


def _operator_steps(
    *,
    plan_digest: str,
    staged_diff_digest: str,
    package_root_cid: str,
    has_verification: bool,
) -> list[dict[str, Any]]:
    """Natural-person steps — every step is human-only and non-automated."""
    common = {
        "requires_human": True,
        "automated_by_this_tool": False,
        "auto_promote": False,
    }
    steps: list[dict[str, Any]] = [
        {
            **common,
            "step_id": "review-evidence",
            "title": "Review staged package evidence",
            "description": (
                "Confirm package_root_cid, plan_digest, staged_diff_digest, "
                "and per-projection digests match the admitted package."
            ),
            "binds": {
                "package_root_cid": package_root_cid,
                "plan_digest": plan_digest,
                "staged_diff_digest": staged_diff_digest,
            },
        },
        {
            **common,
            "step_id": "sign-approval",
            "title": "Sign exact-digest operator approval",
            "description": (
                "Natural person signs an HMAC approval binding plan_digest, "
                "staged_diff_digest, and package_root_cid (release_root_cid). "
                "Agents and supervisors cannot self-approve."
            ),
            "binds": {
                "plan_digest": plan_digest,
                "staged_diff_digest": staged_diff_digest,
                "package_root_cid": package_root_cid,
            },
        },
        {
            **common,
            "step_id": "promote",
            "title": "Promote approved staged commits",
            "description": (
                "Natural person runs the stage CLI promote mode with the signed "
                "approval and staged receipt only. No auto-promote path exists."
            ),
            "binds": {
                "plan_digest": plan_digest,
                "staged_diff_digest": staged_diff_digest,
            },
        },
        {
            **common,
            "step_id": "pin-verify",
            "title": "Pin and redownload-verify promoted artifacts",
            "description": (
                "After promote, pin each promoted commit SHA and redownload "
                "corpus / BM25 / vectors / knowledge_graph artifacts; compare "
                "digests to the staged package."
            ),
            "binds": {
                "package_root_cid": package_root_cid,
                "verification_prebound": has_verification,
            },
        },
        {
            **common,
            "step_id": "canary",
            "title": "Run post-promote Viewer / retrieval canary",
            "description": (
                "Natural person runs a content-free canary against pinned "
                "revisions only (never main/latest/HEAD)."
            ),
            "binds": {
                "unpinned_revision_rejected": True,
            },
        },
        {
            **common,
            "step_id": "rollback",
            "title": "Prepare rollback pointer (if needed)",
            "description": (
                "If pin-verify or canary fails, move only an approved pointer "
                "back to the prior pinned SHA. Never delete evidence."
            ),
            "binds": {
                "pointers_moved_by_checklist": False,
            },
        },
    ]
    return steps


def build_promote_checklist(
    *,
    stage_receipt: Mapping[str, Any],
    verification_receipt: Mapping[str, Any] | None = None,
    admission_receipt: Mapping[str, Any] | None = None,
    package_manifest: Mapping[str, Any] | None = None,
    stage_receipt_path: str = "",
    verification_receipt_path: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a content-free promote checklist from stage (+ optional) receipts."""
    try:
        reject_credentials_in_payload(stage_receipt, label="stage_receipt")
        if verification_receipt is not None:
            reject_credentials_in_payload(
                verification_receipt, label="verification_receipt"
            )
        if admission_receipt is not None:
            reject_credentials_in_payload(
                admission_receipt, label="admission_receipt"
            )
        if package_manifest is not None:
            reject_credentials_in_payload(
                package_manifest, label="package_manifest"
            )
    except CredentialLeakError as exc:
        raise PromoteChecklistError(str(exc)) from exc

    package_root_cid = _optional_digest(
        stage_receipt.get("package_root_cid")
        or stage_receipt.get("release_root_cid")
        or (package_manifest or {}).get("package_root_cid"),
        label="package_root_cid",
        require=True,
    )
    plan_digest = _optional_digest(
        stage_receipt.get("plan_digest")
        or stage_receipt.get("plan_digest_bound"),
        label="plan_digest",
        require=True,
    )
    staged_diff_digest = _optional_digest(
        stage_receipt.get("staged_diff_digest")
        or stage_receipt.get("staged_diff_digest_bound"),
        label="staged_diff_digest",
        require=True,
    )

    # Reject floating target revisions if present.
    for key in (
        "target_revision",
        "promoted_revision",
        "default_branch",
        "revision",
    ):
        if key in stage_receipt:
            _reject_unpinned(stage_receipt.get(key), label=key)

    projection_digests = _extract_projection_digests(stage_receipt)
    if verification_receipt is not None:
        for family, digests in _extract_projection_digests(
            verification_receipt
        ).items():
            projection_digests.setdefault(family, {}).update(digests)

    if package_manifest is not None:
        for family, key in (
            ("corpus", "corpus_root_cid"),
            ("bm25", "bm25_root_cid"),
            ("vectors", "vector_root_cid"),
            ("knowledge_graph", "graph_root_cid"),
        ):
            val = _optional_digest(package_manifest.get(key), label=key)
            if val:
                projection_digests.setdefault(family, {})["root_cid"] = val

    staged_repos = _extract_staged_repositories(stage_receipt)

    evidence_gaps: list[dict[str, str]] = []
    for family in PROJECTION_FAMILIES:
        if family not in projection_digests:
            evidence_gaps.append(
                {
                    "kind": "missing_projection_digest",
                    "family": family,
                    "reason": f"no digest bound for projection {family}",
                }
            )
    if not staged_repos:
        evidence_gaps.append(
            {
                "kind": "missing_staged_repositories",
                "reason": "stage receipt has no repositories with staged commit SHAs",
            }
        )
    else:
        for repo in staged_repos:
            if not repo.get("staged_commit_sha"):
                evidence_gaps.append(
                    {
                        "kind": "missing_staged_commit_sha",
                        "dataset_id": str(repo.get("dataset_id") or ""),
                        "reason": "repository missing staged_commit_sha",
                    }
                )

    has_verification = verification_receipt is not None
    verification_status = ""
    if has_verification:
        verification_status = _text(
            verification_receipt.get("status")
            or verification_receipt.get("verification_status")
            or "present"
        )
        # Cross-check package root when present.
        v_root = _optional_digest(
            verification_receipt.get("package_root_cid")
            or verification_receipt.get("release_root_cid"),
            label="verification.package_root_cid",
        )
        if v_root and v_root != package_root_cid:
            evidence_gaps.append(
                {
                    "kind": "verification_package_root_mismatch",
                    "reason": (
                        f"verification package_root_cid {v_root!r} != "
                        f"stage {package_root_cid!r}"
                    ),
                }
            )
    else:
        evidence_gaps.append(
            {
                "kind": "verification_receipt_absent",
                "reason": (
                    "optional PATLAW-177 pin-verify receipt not supplied; "
                    "pin-verify remains a required human step after promote"
                ),
            }
        )

    if admission_receipt is not None:
        a_root = _optional_digest(
            admission_receipt.get("package_root_cid"),
            label="admission.package_root_cid",
        )
        if a_root and a_root != package_root_cid:
            evidence_gaps.append(
                {
                    "kind": "admission_package_root_mismatch",
                    "reason": (
                        f"admission package_root_cid {a_root!r} != "
                        f"stage {package_root_cid!r}"
                    ),
                }
            )

    steps = _operator_steps(
        plan_digest=plan_digest,
        staged_diff_digest=staged_diff_digest,
        package_root_cid=package_root_cid,
        has_verification=has_verification,
    )

    organization = _text(
        stage_receipt.get("organization")
        or (package_manifest or {}).get("organization")
    )
    version_tag = _text(
        stage_receipt.get("version_tag")
        or (package_manifest or {}).get("version_tag")
    )
    release_id = _text(stage_receipt.get("release_id"))
    branch_name = _text(stage_receipt.get("branch_name"))
    if branch_name:
        _reject_unpinned(branch_name, label="branch_name")

    checklist: dict[str, Any] = {
        "checklist_schema": CHECKLIST_SCHEMA,
        "schema_version": CHECKLIST_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "generated_at": generated_at or _utc_now(),
        "mode": "checklist_only",
        "status": "awaiting_human_promote",
        "disposition": "staged_not_promoted",
        "auto_promote": False,
        "human_approval_required": True,
        "live_network": False,
        "tokens_used": False,
        "main_published": False,
        "pointers_moved": False,
        "unpinned_revision_rejected": True,
        "package_root_cid": package_root_cid,
        "plan_digest": plan_digest,
        "staged_diff_digest": staged_diff_digest,
        "organization": organization,
        "version_tag": version_tag,
        "release_id": release_id,
        "branch_name": branch_name,
        "stage_status": _text(stage_receipt.get("status")),
        "index_families": list(INDEX_FAMILIES),
        "projections": list(PROJECTION_FAMILIES),
        "projection_digests": projection_digests,
        "staged_repositories": staged_repos,
        "verification_bound": has_verification,
        "verification_status": verification_status,
        "evidence": {
            "stage_receipt": stage_receipt_path or "inline",
            "verification_receipt": (
                verification_receipt_path if has_verification else ""
            ),
        },
        "evidence_gaps": evidence_gaps,
        "steps": steps,
        "acceptance": {
            "binds_staged_commit_sha": any(
                bool(r.get("staged_commit_sha")) for r in staged_repos
            ),
            "binds_artifact_digests": bool(projection_digests),
            "documents_natural_person_actions": True,
            "no_auto_promote_path": True,
            "all_steps_require_human": all(
                s.get("requires_human") is True for s in steps
            ),
            "all_steps_not_automated": all(
                s.get("automated_by_this_tool") is False for s in steps
            ),
        },
    }

    # Optional package digest binding.
    pkg_digest = _optional_digest(
        stage_receipt.get("package_digest_sha256")
        or (package_manifest or {}).get("package_digest_sha256"),
        label="package_digest_sha256",
    )
    if pkg_digest:
        checklist["package_digest_sha256"] = pkg_digest

    # Digest over the checklist excluding the digest field itself.
    digest_body = {k: v for k, v in checklist.items() if k != "checklist_digest_sha256"}
    checklist["checklist_digest_sha256"] = _sha256_payload(digest_body)

    try:
        reject_credentials_in_payload(checklist, label="promote_checklist")
    except CredentialLeakError as exc:
        raise PromoteChecklistError(str(exc)) from exc
    _assert_content_free_keys(checklist)

    # Hard invariant: no step may claim automation or auto-promote.
    for step in checklist["steps"]:
        if step.get("auto_promote") is not False:
            raise PromoteChecklistError("step auto_promote must be false")
        if step.get("requires_human") is not True:
            raise PromoteChecklistError("step requires_human must be true")
        if step.get("automated_by_this_tool") is not False:
            raise PromoteChecklistError(
                "step automated_by_this_tool must be false"
            )

    return checklist


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare an exact-digest operator promote checklist for Hub index "
            f"publication ({TASK_ID}). Checklist only — never promotes."
        )
    )
    parser.add_argument(
        "--stage-receipt",
        type=Path,
        required=True,
        help="PATLAW-176 stage or dry-run receipt JSON (binds plan/diff digests)",
    )
    parser.add_argument(
        "--verification-receipt",
        type=Path,
        default=None,
        help="Optional PATLAW-177 pin-verify receipt JSON",
    )
    parser.add_argument(
        "--admission-receipt",
        type=Path,
        default=None,
        help="Optional PATLAW-175 admission receipt JSON",
    )
    parser.add_argument(
        "--package-manifest",
        type=Path,
        default=None,
        help="Optional PATLAW-174 hub-index-package.manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write checklist JSON to this path (default: stdout only)",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print checklist JSON to stdout (default when --output omitted)",
    )
    parser.add_argument(
        "--require-no-gaps",
        action="store_true",
        help="Exit non-zero when evidence_gaps is non-empty",
    )
    parser.add_argument(
        "--fail-on-missing-verification",
        action="store_true",
        help="Exit non-zero when --verification-receipt is omitted",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        stage = _load_json_object(args.stage_receipt)
        verification = (
            _load_json_object(args.verification_receipt)
            if args.verification_receipt is not None
            else None
        )
        admission = (
            _load_json_object(args.admission_receipt)
            if args.admission_receipt is not None
            else None
        )
        package_manifest = (
            _load_json_object(args.package_manifest)
            if args.package_manifest is not None
            else None
        )

        if args.fail_on_missing_verification and verification is None:
            raise EvidenceGapError(
                "--fail-on-missing-verification set but no verification receipt"
            )

        checklist = build_promote_checklist(
            stage_receipt=stage,
            verification_receipt=verification,
            admission_receipt=admission,
            package_manifest=package_manifest,
            stage_receipt_path=str(args.stage_receipt),
            verification_receipt_path=(
                str(args.verification_receipt)
                if args.verification_receipt is not None
                else ""
            ),
        )

        if args.require_no_gaps and checklist.get("evidence_gaps"):
            raise EvidenceGapError(
                "evidence_gaps present: "
                + json.dumps(checklist["evidence_gaps"], sort_keys=True)
            )

        text = json.dumps(checklist, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(
                f"wrote promote checklist: {args.output} "
                f"digest={checklist['checklist_digest_sha256'][:16]}… "
                f"gaps={len(checklist.get('evidence_gaps') or [])}",
                file=sys.stderr,
            )
        if args.print_json or args.output is None:
            sys.stdout.write(text)
        return 0
    except (PromoteChecklistError, CredentialLeakError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
