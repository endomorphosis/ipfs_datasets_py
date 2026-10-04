#!/usr/bin/env python3
"""Seal a Hub index publication receipt distinguishing staged vs promoted (PATLAW-179).

Immutable, content-free receipt for multi-artifact Hub index packages
(corpus + BM25 + vector + knowledge-graph) after pin-verify (PATLAW-177) and
promote-checklist (PATLAW-178).

Policy (fail-closed):

* ``disposition=promoted`` / ``main_published=true`` requires a real promote
  evidence blob (operator promote receipt). Offline mode cannot fabricate
  promoted success without that blob.
* ``disposition=staged_not_promoted`` is a valid, non-vacuous accepted state
  when digests bind corpus plus all three index families.
* Digests always bind corpus, bm25, vectors, and knowledge_graph.
* Never auto-promotes, never performs unattended Hub writes, never moves
  runtime release pointers.

Inputs:

* stage receipt (PATLAW-176) — required
* verification receipt (PATLAW-177) — required for non-blocked seal
* promote checklist (PATLAW-178) — required for non-blocked seal
* promote evidence (optional) — real promote receipt when disposition promoted

Write with ``--output``. Default is offline seal only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (  # noqa: E402
    CredentialLeakError,
    PROMOTION_RECEIPT_SCHEMA,
    reject_credentials_in_payload,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (  # noqa: E402
    INDEX_FAMILIES,
    canonical_json,
)


TASK_ID = "PATLAW-179"
GOAL_ID = "PATLAW-G213"
PROGRAM_ID = "patent-legal-intelligence-v1"
PRODUCER = "seal_patent_legal_hub_index_publication_receipt.py"
CONFIG_ID = "config:hub-index-publication-receipt/v1"
CODE_VERSION = "1"
RECEIPT_SCHEMA = "patent-legal-hub-index-publication-receipt/v1"
INTERFACE = "HubIndexPublicationReceipt@1"

SCHEMA_RELATIVE = (
    "data/release/patent_legal_intelligence/"
    "hub_index_publication_receipt.schema.json"
)

PROJECTION_FAMILIES: tuple[str, ...] = (
    "corpus",
    "bm25",
    "vectors",
    "knowledge_graph",
)

# Schemas / statuses that identify a real promote evidence blob.
_PROMOTE_SCHEMA_MARKERS: frozenset[str] = frozenset(
    {
        PROMOTION_RECEIPT_SCHEMA,
        "patent-legal-hf-promotion-receipt/v2",
        "patent-legal-hub-index-promote-receipt/v1",
        "patent-legal-hub-index-promotion-receipt/v1",
    }
)
_PROMOTE_STATUS_MARKERS: frozenset[str] = frozenset(
    {
        "promoted",
        "promotion_complete",
        "main_published",
    }
)
_STAGE_STATUS_MARKERS: frozenset[str] = frozenset(
    {
        "staged_pending_approval",
        "staged",
        "dry_run_only",
        "awaiting_human_promote",
    }
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_CID_RE = re.compile(r"^(?:bafy|bagu|b[a-z2-7]{20,}|Qm)[a-zA-Z0-9]+$")

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


class PublicationReceiptError(RuntimeError):
    """Fail-closed error for publication receipt sealing."""

    code = "publication_receipt_error"


class EvidenceGapError(PublicationReceiptError):
    code = "evidence_gap"


class FabricatedPromoteError(PublicationReceiptError):
    """Promoted success claimed without a real promote evidence blob."""

    code = "fabricated_promote"


class ContentFreeViolationError(PublicationReceiptError):
    code = "content_free_violation"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


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
    if token.endswith("/head") or token == "refs/heads/head":
        return True
    return False


def _reject_unpinned(value: Any, *, label: str) -> str:
    text = _text(value)
    if _is_unpinned_revision(text):
        raise PublicationReceiptError(
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
    if any(ch.isspace() for ch in text):
        raise PublicationReceiptError(f"{label} must not contain whitespace")
    return text


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    body = canonical_json(dict(payload)).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PublicationReceiptError(f"cannot read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PublicationReceiptError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicationReceiptError(f"expected JSON object in {path}")
    data = dict(payload)
    try:
        reject_credentials_in_payload(data, label=str(path))
    except CredentialLeakError as exc:
        raise PublicationReceiptError(str(exc)) from exc
    return data


def _normalize_family(name: Any) -> str:
    fam = _casefold(name)
    if fam in ("vector", "embedding", "embeddings"):
        return "vectors"
    if fam in ("graph", "kg", "knowledgegraph", "knowledge-graph"):
        return "knowledge_graph"
    return fam


def _extract_projection_digests(
    *sources: Mapping[str, Any] | None,
) -> dict[str, dict[str, str]]:
    """Collect per-projection digests from stage / verify / package sources."""
    out: dict[str, dict[str, str]] = {family: {} for family in PROJECTION_FAMILIES}

    root_map = {
        "corpus": "corpus_root_cid",
        "bm25": "bm25_root_cid",
        "vectors": "vector_root_cid",
        "knowledge_graph": "graph_root_cid",
    }

    for source in sources:
        if source is None:
            continue
        for family, key in root_map.items():
            val = _optional_digest(source.get(key), label=key)
            if val:
                out[family].setdefault("root_cid", val)
                out[family].setdefault("source", "root_cid_field")

        nested = source.get("projection_digests") or source.get("projections")
        if isinstance(nested, Mapping):
            for family, blob in nested.items():
                fam = _normalize_family(family)
                if fam not in out:
                    continue
                if isinstance(blob, Mapping):
                    root = _optional_digest(
                        blob.get("root_cid") or blob.get("cid"),
                        label=f"projection_digests.{fam}.root_cid",
                    )
                    if root:
                        out[fam]["root_cid"] = root
                    digest = _optional_digest(
                        blob.get("digest_sha256")
                        or blob.get("sha256")
                        or blob.get("digest"),
                        label=f"projection_digests.{fam}.digest",
                    )
                    if digest and _HEX64_RE.fullmatch(digest):
                        out[fam]["digest_sha256"] = digest
                        out[fam]["sha256"] = digest
                    # Path-keyed digest maps from verify receipts.
                    for k, v in blob.items():
                        if k in {
                            "root_cid",
                            "cid",
                            "digest_sha256",
                            "sha256",
                            "digest",
                            "source",
                        }:
                            continue
                        dig = _optional_digest(
                            v, label=f"projection_digests.{fam}.{k}"
                        )
                        if dig and _HEX64_RE.fullmatch(dig):
                            out[fam].setdefault("digest_sha256", dig)
                            out[fam].setdefault("sha256", dig)
                else:
                    dig = _optional_digest(
                        blob, label=f"projection_digests.{fam}"
                    )
                    if dig:
                        if _HEX64_RE.fullmatch(dig):
                            out[fam]["digest_sha256"] = dig
                            out[fam]["sha256"] = dig
                        else:
                            out[fam].setdefault("root_cid", dig)

        # Direct package-style root fields already handled; also package digest.
        pkg = _optional_digest(
            source.get("package_digest_sha256"),
            label="package_digest_sha256",
        )
        if pkg and _HEX64_RE.fullmatch(pkg):
            # Not a projection; carried separately by caller.
            pass

    return out


def _extract_staged_repositories(
    stage_receipt: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw = (
        stage_receipt.get("repositories")
        or stage_receipt.get("staged_repositories")
        or ()
    )
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
            raise PublicationReceiptError(
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


def _evidence_digest(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return _sha256_payload(payload)


def _is_promote_evidence(payload: Mapping[str, Any]) -> bool:
    """Return True when payload looks like a real promote/promotion receipt."""
    schema = _text(
        payload.get("schema_version") or payload.get("receipt_schema")
    )
    status = _casefold(payload.get("status"))
    if schema in _PROMOTE_SCHEMA_MARKERS:
        return True
    if "promotion" in schema.casefold() and "stage" not in schema.casefold():
        return True
    if status in _PROMOTE_STATUS_MARKERS:
        return True
    if payload.get("main_published") is True and (
        payload.get("approval_id") or payload.get("repositories")
    ):
        # main_published alone is not enough without approval/repos structure;
        # require at least one promote-shaped signal already handled above.
        repos = payload.get("repositories") or ()
        if isinstance(repos, (list, tuple)) and any(
            isinstance(r, Mapping) and r.get("promoted_commit_sha") for r in repos
        ):
            return True
    return False


def _is_stage_shaped(payload: Mapping[str, Any]) -> bool:
    schema = _casefold(
        payload.get("schema_version") or payload.get("receipt_schema")
    )
    status = _casefold(payload.get("status"))
    if "stage" in schema and "promotion" not in schema:
        return True
    if status in _STAGE_STATUS_MARKERS:
        return True
    if payload.get("main_published") is False and not payload.get("approval_id"):
        repos = payload.get("repositories") or ()
        if isinstance(repos, (list, tuple)) and any(
            isinstance(r, Mapping) and r.get("staged_commit_sha") and not r.get(
                "promoted_commit_sha"
            )
            for r in repos
        ):
            return True
    return False


def _validate_promote_evidence(
    *,
    promote_evidence: Mapping[str, Any],
    package_root_cid: str,
    plan_digest: str,
    staged_diff_digest: str,
) -> dict[str, Any]:
    """Validate a real promote evidence blob; raise on fabrication/mismatch."""
    try:
        reject_credentials_in_payload(promote_evidence, label="promote_evidence")
    except CredentialLeakError as exc:
        raise PublicationReceiptError(str(exc)) from exc

    if _is_stage_shaped(promote_evidence) and not _is_promote_evidence(
        promote_evidence
    ):
        raise FabricatedPromoteError(
            "promote evidence is stage-shaped and does not qualify as a "
            "promotion receipt; cannot claim promoted disposition"
        )
    if not _is_promote_evidence(promote_evidence):
        raise FabricatedPromoteError(
            "promote evidence does not match a known promotion receipt shape "
            f"(expected schema like {PROMOTION_RECEIPT_SCHEMA!r} or "
            "status=promoted with promoted_commit_sha repositories)"
        )

    status = _casefold(promote_evidence.get("status"))
    if status and status not in _PROMOTE_STATUS_MARKERS and status not in {
        "accepted",
        "ok",
        "success",
    }:
        # Allow explicit success statuses; reject staged statuses.
        if status in _STAGE_STATUS_MARKERS:
            raise FabricatedPromoteError(
                f"promote evidence status {status!r} is not a promoted success"
            )

    pe_root = _optional_digest(
        promote_evidence.get("package_root_cid")
        or promote_evidence.get("release_root_cid"),
        label="promote_evidence.package_root_cid",
    )
    if pe_root and pe_root != package_root_cid:
        raise EvidenceGapError(
            f"promote evidence package_root_cid {pe_root!r} != "
            f"stage {package_root_cid!r}"
        )

    pe_plan = _optional_digest(
        promote_evidence.get("plan_digest"),
        label="promote_evidence.plan_digest",
    )
    if pe_plan and pe_plan != plan_digest:
        raise EvidenceGapError(
            f"promote evidence plan_digest mismatch vs stage"
        )

    pe_diff = _optional_digest(
        promote_evidence.get("staged_diff_digest"),
        label="promote_evidence.staged_diff_digest",
    )
    if pe_diff and pe_diff != staged_diff_digest:
        raise EvidenceGapError(
            f"promote evidence staged_diff_digest mismatch vs stage"
        )

    repos_raw = promote_evidence.get("repositories") or ()
    promoted_repos: list[dict[str, Any]] = []
    if isinstance(repos_raw, (list, tuple)):
        for item in repos_raw:
            if not isinstance(item, Mapping):
                continue
            dataset_id = _text(item.get("dataset_id"))
            promoted_sha = _reject_unpinned(
                item.get("promoted_commit_sha") or item.get("commit_sha"),
                label=f"promote_evidence.repositories[{dataset_id}].promoted_commit_sha",
            )
            if not promoted_sha:
                continue
            if not (_HEX40_RE.fullmatch(promoted_sha) or _HEX64_RE.fullmatch(promoted_sha)):
                # Still accept opaque non-floating SHAs that passed unpinned check.
                pass
            entry: dict[str, Any] = {
                "dataset_id": dataset_id,
                "promoted_commit_sha": promoted_sha.casefold(),
            }
            parent = _reject_unpinned(
                item.get("parent_commit"),
                label=f"promote_evidence.repositories[{dataset_id}].parent_commit",
            )
            if parent:
                entry["parent_commit"] = parent.casefold()
            target = _text(item.get("target_revision"))
            if target:
                # target_revision may be a branch name on the remote after
                # promote (e.g. main) — record but do not treat as pin identity.
                entry["target_revision"] = target
            promoted_repos.append(entry)

    if not promoted_repos and not promote_evidence.get("approval_id"):
        raise FabricatedPromoteError(
            "promote evidence lacks promoted_commit_sha repositories and "
            "approval_id; not a real promote blob"
        )

    main_published = bool(promote_evidence.get("main_published"))
    if status in _PROMOTE_STATUS_MARKERS:
        main_published = main_published or True
    # Prefer explicit main_published from evidence; status=promoted implies it.
    if status in {"promoted", "promotion_complete", "main_published"}:
        main_published = True if promote_evidence.get("main_published") is not False else main_published
        if promote_evidence.get("main_published") is None:
            main_published = True

    return {
        "validated": True,
        "status": _text(promote_evidence.get("status")) or "promoted",
        "schema_version": _text(
            promote_evidence.get("schema_version")
            or promote_evidence.get("receipt_schema")
        ),
        "approval_id": _text(promote_evidence.get("approval_id")),
        "main_published": bool(main_published),
        "live_network": bool(promote_evidence.get("live_network")),
        "fake_service": bool(promote_evidence.get("fake_service")),
        "package_root_cid": pe_root or package_root_cid,
        "repository_count": len(promoted_repos),
        "promoted_repositories": promoted_repos,
        "digest_sha256": _evidence_digest(promote_evidence),
    }


def _projection_complete(projection_digests: Mapping[str, Mapping[str, str]]) -> bool:
    for family in PROJECTION_FAMILIES:
        entry = projection_digests.get(family) or {}
        if not entry.get("root_cid"):
            return False
    return True


def _index_families_complete(
    projection_digests: Mapping[str, Mapping[str, str]],
) -> bool:
    for family in INDEX_FAMILIES:
        entry = projection_digests.get(family) or {}
        if not entry.get("root_cid"):
            return False
    return True


def seal_publication_receipt(
    *,
    stage_receipt: Mapping[str, Any],
    verification_receipt: Mapping[str, Any] | None = None,
    promote_checklist: Mapping[str, Any] | None = None,
    promote_evidence: Mapping[str, Any] | None = None,
    package_manifest: Mapping[str, Any] | None = None,
    stage_receipt_path: str = "",
    verification_receipt_path: str = "",
    promote_checklist_path: str = "",
    promote_evidence_path: str = "",
    mode: str = "offline",
    sealed_at_utc: str | None = None,
    receipt_id: str | None = None,
    claim_promoted: bool = False,
    require_verification: bool = True,
    require_checklist: bool = True,
) -> dict[str, Any]:
    """Seal an immutable staged-vs-promoted Hub index publication receipt.

    Parameters
    ----------
    claim_promoted:
        When True, the caller explicitly requests a promoted disposition.
        Fail closed unless ``promote_evidence`` validates. Offline mode may
        still seal promoted **only** when a real promote evidence blob is
        supplied (e.g. fake-service promote receipt).
    """
    mode_norm = _casefold(mode) or "offline"
    if mode_norm not in {"offline", "live"}:
        raise PublicationReceiptError(
            f"mode must be 'offline' or 'live', got {mode!r}"
        )

    for label, blob in (
        ("stage_receipt", stage_receipt),
        ("verification_receipt", verification_receipt),
        ("promote_checklist", promote_checklist),
        ("promote_evidence", promote_evidence),
        ("package_manifest", package_manifest),
    ):
        if blob is None:
            continue
        try:
            reject_credentials_in_payload(blob, label=label)
        except CredentialLeakError as exc:
            raise PublicationReceiptError(str(exc)) from exc

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

    for key in (
        "target_revision",
        "promoted_revision",
        "default_branch",
        "revision",
    ):
        if key in stage_receipt:
            _reject_unpinned(stage_receipt.get(key), label=key)

    projection_digests = _extract_projection_digests(
        stage_receipt,
        verification_receipt,
        package_manifest,
        promote_checklist,
    )
    # Normalize to required shape for schema (all four families present as keys).
    normalized_projections: dict[str, dict[str, str]] = {}
    for family in PROJECTION_FAMILIES:
        entry = dict(projection_digests.get(family) or {})
        if "root_cid" not in entry:
            entry.setdefault("root_cid", "")
        normalized_projections[family] = entry

    staged_repos = _extract_staged_repositories(stage_receipt)

    evidence_gaps: list[dict[str, str]] = []
    blockers: list[str] = []

    for family in PROJECTION_FAMILIES:
        if not (normalized_projections.get(family) or {}).get("root_cid"):
            evidence_gaps.append(
                {
                    "kind": "missing_projection_digest",
                    "family": family,
                    "reason": f"no root_cid bound for projection {family}",
                }
            )

    has_verification = verification_receipt is not None
    has_checklist = promote_checklist is not None
    if not has_verification:
        evidence_gaps.append(
            {
                "kind": "verification_receipt_absent",
                "reason": "PATLAW-177 verification receipt not supplied",
            }
        )
        if require_verification:
            blockers.append("verification_receipt_required")
    else:
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
            blockers.append("verification_package_root_mismatch")

    if not has_checklist:
        evidence_gaps.append(
            {
                "kind": "promote_checklist_absent",
                "reason": "PATLAW-178 promote checklist not supplied",
            }
        )
        if require_checklist:
            blockers.append("promote_checklist_required")
    else:
        c_root = _optional_digest(
            promote_checklist.get("package_root_cid")
            or promote_checklist.get("release_root_cid"),
            label="checklist.package_root_cid",
        )
        if c_root and c_root != package_root_cid:
            evidence_gaps.append(
                {
                    "kind": "checklist_package_root_mismatch",
                    "reason": (
                        f"checklist package_root_cid {c_root!r} != "
                        f"stage {package_root_cid!r}"
                    ),
                }
            )
            blockers.append("checklist_package_root_mismatch")

    digests_bind_index = _index_families_complete(normalized_projections)
    digests_bind_corpus = bool(
        (normalized_projections.get("corpus") or {}).get("root_cid")
    )
    digests_complete = digests_bind_index and digests_bind_corpus
    non_vacuous = digests_complete and bool(plan_digest) and bool(
        staged_diff_digest
    ) and bool(package_root_cid)

    if not digests_complete:
        blockers.append("projection_digests_incomplete")

    # --- Promote evidence / disposition ---------------------------------
    promote_meta: dict[str, Any] | None = None
    promoted_repos: list[dict[str, Any]] = []
    disposition = "staged_not_promoted"
    main_published = False
    publication_promoted = False
    publication_asserted = False
    promote_present = promote_evidence is not None
    promote_validated = False

    # Explicit claim without evidence is always fabricated.
    if claim_promoted and promote_evidence is None:
        raise FabricatedPromoteError(
            "cannot claim promoted success without a real promote evidence blob "
            f"(mode={mode_norm})"
        )

    # Stage receipt itself must never be treated as promote success.
    if stage_receipt.get("main_published") is True and promote_evidence is None:
        raise FabricatedPromoteError(
            "stage receipt claims main_published without promote evidence"
        )

    if promote_evidence is not None:
        promote_meta = _validate_promote_evidence(
            promote_evidence=promote_evidence,
            package_root_cid=package_root_cid,
            plan_digest=plan_digest,
            staged_diff_digest=staged_diff_digest,
        )
        promote_validated = True
        disposition = "promoted"
        main_published = bool(promote_meta.get("main_published"))
        publication_promoted = True
        publication_asserted = True
        promoted_repos = list(promote_meta.get("promoted_repositories") or [])
    elif claim_promoted:
        # Unreachable due to earlier check; keep for clarity.
        raise FabricatedPromoteError(
            "promoted disposition requires promote evidence"
        )
    else:
        # Offline (or live) staged-only: never invent promoted success.
        disposition = "staged_not_promoted"
        main_published = False
        publication_promoted = False
        publication_asserted = False

    # Offline still allows promoted when real evidence blob is present
    # (e.g. fake-service promote). Fabrication is only when evidence is missing.

    # Status: accepted when non-vacuous and no hard blockers; else blocked.
    hard_blockers = list(blockers)
    # Missing promote evidence is NOT a blocker for staged-only.
    if disposition == "promoted" and not promote_validated:
        hard_blockers.append("promote_evidence_invalid")

    if hard_blockers:
        status = "blocked"
    elif not non_vacuous:
        status = "blocked"
        hard_blockers.append("vacuous_receipt")
    else:
        status = "accepted"

    # For schema compliance on blocked receipts that lack projection roots,
    # fill empty root_cid with a sentinel only if we would fail schema —
    # instead fail closed by raising when digests incomplete and status would
    # need schema-valid empty roots. Prefer raising EvidenceGapError for
    # incomplete digests when sealing is attempted for acceptance path.
    if not digests_complete:
        missing = [
            f
            for f in PROJECTION_FAMILIES
            if not (normalized_projections.get(f) or {}).get("root_cid")
        ]
        raise EvidenceGapError(
            "projection digests incomplete; cannot seal non-vacuous receipt. "
            f"missing root_cid for: {', '.join(missing)}"
        )

    organization = _text(
        stage_receipt.get("organization")
        or (package_manifest or {}).get("organization")
        or (promote_checklist or {}).get("organization")
    )
    version_tag = _text(
        stage_receipt.get("version_tag")
        or (package_manifest or {}).get("version_tag")
        or (promote_checklist or {}).get("version_tag")
    )
    release_id = _text(
        stage_receipt.get("release_id")
        or (promote_checklist or {}).get("release_id")
    )
    release_root_cid = _optional_digest(
        stage_receipt.get("release_root_cid") or package_root_cid,
        label="release_root_cid",
    )
    branch_name = _text(
        stage_receipt.get("branch_name")
        or (promote_checklist or {}).get("branch_name")
    )
    if branch_name:
        _reject_unpinned(branch_name, label="branch_name")

    package_digest = _optional_digest(
        stage_receipt.get("package_digest_sha256")
        or (package_manifest or {}).get("package_digest_sha256")
        or (promote_checklist or {}).get("package_digest_sha256"),
        label="package_digest_sha256",
    )

    sealed_at = sealed_at_utc or _utc_now()
    rid = receipt_id or f"hub-index-pub-{uuid.uuid4().hex[:16]}"

    stage_status = _text(stage_receipt.get("status"))
    verify_status = ""
    if has_verification:
        verify_status = _text(
            verification_receipt.get("status")
            or verification_receipt.get("verification_status")
            or "present"
        )
    checklist_disposition = ""
    checklist_status = ""
    if has_checklist:
        checklist_disposition = _text(
            promote_checklist.get("disposition") or "staged_not_promoted"
        )
        checklist_status = _text(promote_checklist.get("status") or "present")

    evidence_block = {
        "stage_receipt": {
            "present": True,
            "path": stage_receipt_path or "inline",
            "digest_sha256": _evidence_digest(stage_receipt),
            "status": stage_status,
            "schema_version": _text(
                stage_receipt.get("receipt_schema")
                or stage_receipt.get("schema_version")
            ),
            "package_root_cid": package_root_cid,
        },
        "verification_receipt": {
            "present": has_verification,
            "path": verification_receipt_path if has_verification else "",
            "digest_sha256": _evidence_digest(verification_receipt),
            "status": verify_status,
            "schema_version": (
                _text(
                    verification_receipt.get("schema_version")
                    or verification_receipt.get("receipt_schema")
                )
                if has_verification
                else ""
            ),
            "package_root_cid": (
                _optional_digest(
                    verification_receipt.get("package_root_cid")
                    or verification_receipt.get("release_root_cid"),
                    label="verification.package_root_cid",
                )
                if has_verification
                else ""
            ),
            "validated": has_verification
            and "verification_package_root_mismatch" not in hard_blockers,
        },
        "promote_checklist": {
            "present": has_checklist,
            "path": promote_checklist_path if has_checklist else "",
            "digest_sha256": _evidence_digest(promote_checklist),
            "status": checklist_status,
            "disposition": checklist_disposition,
            "schema_version": (
                _text(
                    promote_checklist.get("checklist_schema")
                    or promote_checklist.get("schema_version")
                )
                if has_checklist
                else ""
            ),
            "package_root_cid": (
                _optional_digest(
                    promote_checklist.get("package_root_cid"),
                    label="checklist.package_root_cid",
                )
                if has_checklist
                else ""
            ),
            "validated": has_checklist
            and "checklist_package_root_mismatch" not in hard_blockers,
        },
        "promote_evidence": {
            "present": promote_present,
            "path": promote_evidence_path if promote_present else "",
            "digest_sha256": (
                promote_meta.get("digest_sha256") if promote_meta else None
            ),
            "status": promote_meta.get("status", "") if promote_meta else "",
            "schema_version": (
                promote_meta.get("schema_version", "") if promote_meta else ""
            ),
            "validated": promote_validated,
            "approval_id": (
                promote_meta.get("approval_id", "") if promote_meta else ""
            ),
            "main_published": main_published if promote_validated else False,
            "live_network": (
                bool(promote_meta.get("live_network")) if promote_meta else False
            ),
            "fake_service": (
                bool(promote_meta.get("fake_service")) if promote_meta else False
            ),
            "package_root_cid": package_root_cid if promote_validated else "",
            "repository_count": (
                int(promote_meta.get("repository_count") or 0)
                if promote_meta
                else 0
            ),
        },
    }

    fake_service = bool(
        (promote_meta or {}).get("fake_service")
        or stage_receipt.get("fake_service")
    )
    live_network = mode_norm == "live" or bool(
        (promote_meta or {}).get("live_network")
    )
    # Sealer itself never contacts the network.
    if mode_norm == "offline":
        live_network = False

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "interface": INTERFACE,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "config_id": CONFIG_ID,
        "code_version": CODE_VERSION,
        "receipt_id": rid,
        "sealed_at_utc": sealed_at,
        "mode": mode_norm,
        "disposition": disposition,
        "status": status,
        "package_root_cid": package_root_cid,
        "package_digest_sha256": package_digest or None,
        "plan_digest": plan_digest,
        "staged_diff_digest": staged_diff_digest,
        "organization": organization,
        "version_tag": version_tag,
        "release_id": release_id,
        "release_root_cid": release_root_cid or package_root_cid,
        "branch_name": branch_name,
        "index_families": list(INDEX_FAMILIES),
        "index_families_present": list(INDEX_FAMILIES),
        "projections": list(PROJECTION_FAMILIES),
        "projection_digests": {
            family: {
                k: v
                for k, v in normalized_projections[family].items()
                if v not in ("", None)
            }
            for family in PROJECTION_FAMILIES
        },
        "staged_repositories": staged_repos,
        "promoted_repositories": promoted_repos,
        "evidence": evidence_block,
        "publication_claim": {
            "asserted": publication_asserted,
            "promoted": publication_promoted,
            "main_published": main_published,
            "reviewed_promote_evidence_present": promote_validated,
            "offline_promoted_without_evidence_forbidden": True,
            "content_free": True,
        },
        "main_published": main_published,
        "pointers_moved": False,
        "live_network": live_network,
        "tokens_used": False,
        "auto_promote": False,
        "unattended_hub_write": False,
        "fake_service": fake_service,
        "evidence_gaps": evidence_gaps,
        "blockers": hard_blockers,
        "notes": [],
        "acceptance": {
            "staged_only_valid": disposition == "staged_not_promoted"
            and status == "accepted",
            "promoted_requires_evidence": True,
            "digests_bind_all_index_families": digests_bind_index,
            "digests_bind_corpus": digests_bind_corpus,
            "non_vacuous": non_vacuous and status == "accepted",
            "no_fabricated_promote": not (
                publication_promoted and not promote_validated
            ),
            "no_unattended_hub_write": True,
            "verification_bound": has_verification,
            "checklist_bound": has_checklist,
            "promote_evidence_bound": promote_validated,
        },
        "policy": {
            "fail_closed": True,
            "content_free": True,
            "promoted_requires_real_evidence": True,
            "staged_only_non_vacuous": True,
            "no_auto_promote": True,
            "no_unattended_hub_write": True,
            "offline_cannot_fabricate_promote": True,
            "pointers_never_moved_by_sealer": True,
            "required_projections": list(PROJECTION_FAMILIES),
            "required_index_families": list(INDEX_FAMILIES),
        },
        "content_free": True,
    }

    if disposition == "staged_not_promoted":
        receipt["notes"].append(
            "staged_not_promoted is a valid non-vacuous publication state; "
            "promote remains an operator action outside this sealer"
        )
    else:
        receipt["notes"].append(
            "promoted disposition sealed only because promote evidence blob "
            "validated against stage digests"
        )

    # Ensure every projection entry retains root_cid for schema.
    for family in PROJECTION_FAMILIES:
        if "root_cid" not in receipt["projection_digests"][family]:
            raise EvidenceGapError(
                f"internal error: projection {family} lost root_cid"
            )

    digest_body = {
        k: v for k, v in receipt.items() if k != "receipt_digest_sha256"
    }
    receipt["receipt_digest_sha256"] = _sha256_payload(digest_body)

    try:
        reject_credentials_in_payload(receipt, label="publication_receipt")
    except CredentialLeakError as exc:
        raise PublicationReceiptError(str(exc)) from exc

    # Hard invariants.
    if receipt["disposition"] == "promoted":
        if not receipt["evidence"]["promote_evidence"]["validated"]:
            raise FabricatedPromoteError(
                "invariant: promoted disposition without validated evidence"
            )
        if not receipt["publication_claim"]["reviewed_promote_evidence_present"]:
            raise FabricatedPromoteError(
                "invariant: promoted claim missing reviewed evidence flag"
            )
    if receipt["disposition"] == "staged_not_promoted":
        if receipt["main_published"] is not False:
            raise FabricatedPromoteError(
                "invariant: staged_not_promoted must have main_published=false"
            )
        if receipt["publication_claim"]["promoted"] is not False:
            raise FabricatedPromoteError(
                "invariant: staged_not_promoted must not claim promoted"
            )
    if receipt["auto_promote"] is not False:
        raise PublicationReceiptError("auto_promote must be false")
    if receipt["unattended_hub_write"] is not False:
        raise PublicationReceiptError("unattended_hub_write must be false")
    if receipt["pointers_moved"] is not False:
        raise PublicationReceiptError("pointers_moved must be false")
    if receipt["tokens_used"] is not False:
        raise PublicationReceiptError("tokens_used must be false")

    return receipt


def load_schema(schema_path: Path | None = None) -> dict[str, Any]:
    path = schema_path or (REPOSITORY_ROOT / SCHEMA_RELATIVE)
    return _load_json_object(path)


def validate_receipt_against_schema(
    receipt: Mapping[str, Any],
    *,
    schema: Mapping[str, Any] | None = None,
    schema_path: Path | None = None,
) -> None:
    """Validate receipt with jsonschema Draft 2020-12 (fail-closed)."""
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover
        raise PublicationReceiptError(
            "jsonschema is required to validate publication receipts"
        ) from exc

    schema_obj = schema if schema is not None else load_schema(schema_path)
    validator = Draft202012Validator(schema_obj)
    errors = sorted(validator.iter_errors(dict(receipt)), key=lambda e: list(e.path))
    if errors:
        messages = []
        for err in errors[:8]:
            path = ".".join(str(p) for p in err.path) or "<root>"
            messages.append(f"{path}: {err.message}")
        raise PublicationReceiptError(
            "receipt failed schema validation: " + "; ".join(messages)
        )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seal a Hub index publication receipt distinguishing staged vs "
            f"promoted ({TASK_ID}). Never fabricates promoted success offline "
            "without a real promote evidence blob."
        )
    )
    parser.add_argument(
        "--stage-receipt",
        type=Path,
        required=True,
        help="PATLAW-176 stage or dry-run receipt JSON",
    )
    parser.add_argument(
        "--verification-receipt",
        type=Path,
        default=None,
        help="PATLAW-177 pin-verify receipt JSON (required unless --allow-missing-verification)",
    )
    parser.add_argument(
        "--promote-checklist",
        type=Path,
        default=None,
        help="PATLAW-178 promote checklist JSON (required unless --allow-missing-checklist)",
    )
    parser.add_argument(
        "--promote-evidence",
        type=Path,
        default=None,
        help=(
            "Optional real promote receipt JSON (PATLAW-176 --mode promote). "
            "Required for disposition=promoted / --claim-promoted."
        ),
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
        help="Write sealed receipt JSON to this path",
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="Seal mode (default offline). Offline cannot fabricate promote.",
    )
    parser.add_argument(
        "--claim-promoted",
        action="store_true",
        help=(
            "Explicitly request promoted disposition; fails closed without "
            "--promote-evidence"
        ),
    )
    parser.add_argument(
        "--allow-missing-verification",
        action="store_true",
        help="Do not hard-block when --verification-receipt is omitted",
    )
    parser.add_argument(
        "--allow-missing-checklist",
        action="store_true",
        help="Do not hard-block when --promote-checklist is omitted",
    )
    parser.add_argument(
        "--validate-schema",
        action="store_true",
        default=True,
        help="Validate sealed receipt against the schema (default: on)",
    )
    parser.add_argument(
        "--no-validate-schema",
        action="store_true",
        help="Skip schema validation",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help=f"Schema path (default: {SCHEMA_RELATIVE})",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print receipt JSON to stdout",
    )
    parser.add_argument(
        "--require-accepted",
        action="store_true",
        help="Exit non-zero when status is not accepted",
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
        checklist = (
            _load_json_object(args.promote_checklist)
            if args.promote_checklist is not None
            else None
        )
        promote_evidence = (
            _load_json_object(args.promote_evidence)
            if args.promote_evidence is not None
            else None
        )
        package_manifest = (
            _load_json_object(args.package_manifest)
            if args.package_manifest is not None
            else None
        )

        if (
            args.claim_promoted or promote_evidence is not None
        ) and promote_evidence is None and args.claim_promoted:
            raise FabricatedPromoteError(
                "--claim-promoted requires --promote-evidence"
            )

        receipt = seal_publication_receipt(
            stage_receipt=stage,
            verification_receipt=verification,
            promote_checklist=checklist,
            promote_evidence=promote_evidence,
            package_manifest=package_manifest,
            stage_receipt_path=str(args.stage_receipt),
            verification_receipt_path=(
                str(args.verification_receipt)
                if args.verification_receipt is not None
                else ""
            ),
            promote_checklist_path=(
                str(args.promote_checklist)
                if args.promote_checklist is not None
                else ""
            ),
            promote_evidence_path=(
                str(args.promote_evidence)
                if args.promote_evidence is not None
                else ""
            ),
            mode=args.mode,
            claim_promoted=bool(args.claim_promoted),
            require_verification=not args.allow_missing_verification,
            require_checklist=not args.allow_missing_checklist,
        )

        do_validate = args.validate_schema and not args.no_validate_schema
        if do_validate:
            validate_receipt_against_schema(
                receipt, schema_path=args.schema
            )

        if args.output is not None:
            _write_json(args.output, receipt)
        if args.print_json or args.output is None:
            sys.stdout.write(
                json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n"
            )

        if args.require_accepted and receipt.get("status") != "accepted":
            sys.stderr.write(
                f"error: receipt status={receipt.get('status')!r} "
                f"blockers={receipt.get('blockers')}\n"
            )
            return 1
        return 0
    except (
        PublicationReceiptError,
        CredentialLeakError,
    ) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
