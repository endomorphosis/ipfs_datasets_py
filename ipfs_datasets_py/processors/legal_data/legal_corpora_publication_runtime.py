"""Canonical repository and runtime authority for legal-corpora publication (LCR-080).

The in-memory gate (LCR-074) still evaluates a constructed request. This
runtime is the only adapter that may authorize a live mutation: it derives
repository HEAD, task lineage, receipts, candidate manifest, credentials,
and any main seal from **fixed canonical paths** at the actual clean 40-hex
HEAD and rechecks that evidence immediately before invoking a network
callback.

Caller-asserted statuses, receipts, digests, commits, path overrides, or
seals cannot authorize. LCR-083 ``source_rights_binding`` remains a required
gate. This module never contacts the Hub except through a caller-supplied
read-only principal probe and a single upload callback after authorization.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Optional, Sequence, TypeVar, Union

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    AUTHORIZED_DATASET_REPO_IDS,
    BASELINE_REVISIONS,
    FEDERAL_DATASET_REPO_ID,
    PROGRAM_ID as GATE_PROGRAM_ID,
    PublicationGateDecision,
    PublicationGateDeniedError,
    PublicationGateError,
    PublicationPhase,
    REQUIRED_PUBLICATION_GATES,
    RIGHTS_RECEIPT_RELPATH,
    SECRET_ENV_NAMES,
    STATE_DATASET_REPO_ID,
    SUCCESSOR_TASK_ID as GATE_SUCCESSOR_TASK_ID,
    TASK_ID as GATE_TASK_ID,
    credentials_scope_for,
    evaluate_publication_gate,
    normalize_sha256,
    phase_requirements,
    prepublication_seal_required,
    reject_credentials_in_payload,
    require_immutable_revision,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "legal-corpora-publication-runtime-v1"
RUNTIME_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-publication-runtime@1"
TASK_ID: Final = "LCR-080"
GOAL_ID: Final = "LCR-G142"
PROGRAM_ID: Final = GATE_PROGRAM_ID
PRODUCER: Final = "legal_corpora_publication_runtime.py"
PREDECESSOR_GATE_TASK_ID: Final = GATE_TASK_ID
PREDECESSOR_RIGHTS_TASK_ID: Final = GATE_SUCCESSOR_TASK_ID

TOKEN_ENV_ALLOWLIST: Final = SECRET_ENV_NAMES

RECEIPT_SCHEMA_V1: Final = "ipfs_datasets_py/legal-corpora-publication-receipt@1"
MANIFEST_SCHEMA_V1: Final = "ipfs_datasets_py/legal-corpora-candidate-manifest@1"
SEAL_SCHEMA_V1: Final = "ipfs_datasets_py/legal-corpora-prepublication-seal@1"
ALLOWED_RECEIPT_SCHEMAS: Final = frozenset(
    {RECEIPT_SCHEMA_V1, MANIFEST_SCHEMA_V1, SEAL_SCHEMA_V1}
)

RELEASE_POLICY_RELPATH: Final = (
    "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"
)
TASKBOARD_RELPATH: Final = "docs/architecture/legal_corpora_reindex.todo.md"
OBJECTIVES_RELPATH: Final = "docs/architecture/legal_corpora_reindex.objectives.md"
STATE_CANDIDATE_MANIFEST_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
FEDERAL_CANDIDATE_MANIFEST_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
STATE_PREPUBLICATION_SEAL_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/state_prepublication_seal.json"
)
FEDERAL_PREPUBLICATION_SEAL_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
)
STATE_DATASET_CARD_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/state_dataset_card.md"
)
FEDERAL_DATASET_CARD_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_dataset_card.md"
)

CANONICAL_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "release_policy": RELEASE_POLICY_RELPATH,
        "taskboard": TASKBOARD_RELPATH,
        "objectives": OBJECTIVES_RELPATH,
        "state_candidate_manifest": STATE_CANDIDATE_MANIFEST_RELPATH,
        "federal_candidate_manifest": FEDERAL_CANDIDATE_MANIFEST_RELPATH,
        "state_prepublication_seal": STATE_PREPUBLICATION_SEAL_RELPATH,
        "federal_prepublication_seal": FEDERAL_PREPUBLICATION_SEAL_RELPATH,
        "state_dataset_card": STATE_DATASET_CARD_RELPATH,
        "federal_dataset_card": FEDERAL_DATASET_CARD_RELPATH,
        "source_rights_receipt": RIGHTS_RECEIPT_RELPATH,
    }
)

AUTHORITATIVE_OVERRIDE_KEYS: Final = frozenset(
    {
        "branch",
        "claimed_commit",
        "claimed_head",
        "commit",
        "current_commit",
        "expected_receipt_digests",
        "final_manifest_digest",
        "git_ref",
        "goal_parents",
        "manifest_path",
        "objectives_path",
        "path_overrides",
        "paths",
        "prepublication_seal",
        "receipt_paths",
        "receipt_root",
        "receipts",
        "ref",
        "release_policy_path",
        "seal_path",
        "task_dependencies",
        "task_goal_ids",
        "task_statuses",
        "taskboard_path",
    }
)

SELF_DIGEST_FIELDS: Final = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "final_manifest_digest",
        "manifest_digest",
        "no_self_field_digest",
        "raw_sha256",
        "receipt_sha256",
        "sha256",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_Z_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z$")
_TASK_HEADING_RE = re.compile(r"^## (LCR-(?:\d{3}|\d{4,})) (\S.+)$")
_GOAL_HEADING_RE = re.compile(r"^## (LCR-G(?:\d{3}|\d{4,})) (\S.+)$")
_FIELD_LINE_RE = re.compile(r"^- ([^:]+):(.*)$")
_OFFSET_TIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|[+-]\d{4}|Zulu)$"
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
T = TypeVar("T")
PrincipalProbe = Callable[[str, str], Mapping[str, Any]]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicationRuntimeError(PublicationGateError):
    """Base error for canonical runtime failures."""

    code = "publication_runtime_error"


class CanonicalPathOverrideError(PublicationRuntimeError):
    """Raised when a caller tries to override a canonical evidence path."""

    code = "canonical_path_override"


class DirtyAuthoritativePathError(PublicationRuntimeError):
    """Raised when a canonical control or evidence path is dirty."""

    code = "dirty_authoritative_path"


class AlternateRepositoryError(PublicationRuntimeError):
    """Raised when the requested root or branch is not the actual HEAD."""

    code = "alternate_repository"


class CallerCommitError(PublicationRuntimeError):
    """Raised when a caller-selected commit is offered as authority."""

    code = "caller_selected_commit"


class ReceiptSchemaError(PublicationRuntimeError):
    """Raised when a receipt schema is missing or unknown."""

    code = "unknown_receipt_schema"


class ReceiptStatusError(PublicationRuntimeError):
    """Raised when a required receipt omits status."""

    code = "missing_receipt_status"


class IndependentDigestError(PublicationRuntimeError):
    """Raised when declared digests do not match recomputed bytes."""

    code = "independent_digest_mismatch"


class ManifestBindingError(PublicationRuntimeError):
    """Raised when the candidate manifest omits required bindings."""

    code = "missing_manifest_binding"


class CredentialTokenError(PublicationRuntimeError):
    """Raised when the allowlisted token is missing or wrong-scope."""

    code = "credential_token_error"


class PrincipalAuthorityError(PublicationRuntimeError):
    """Raised when the probed principal cannot write the exact target."""

    code = "principal_authority_error"


class SealTimeError(PublicationRuntimeError):
    """Raised when a main seal time is absent, offset, future, or post-mutation."""

    code = "seal_time_error"


class EvidenceRaceError(PublicationRuntimeError):
    """Raised when HEAD or evidence bytes change before the callback."""

    code = "evidence_race"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicationRuntimeError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PublicationRuntimeError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise PublicationRuntimeError(f"{name} exceeds maximum length {maximum}")
    return text


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def raw_file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_no_self_field_digest(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise IndependentDigestError("canonical digest requires a JSON object")
    body = {key: value for key, value in payload.items() if key not in SELF_DIGEST_FIELDS}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _posix_relpath(path: str) -> str:
    text = _require_non_empty_str(path, "path", maximum=1024).replace("\\", "/")
    if text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise CanonicalPathOverrideError(f"unsafe canonical path {path!r}")
    if Path(text).is_absolute():
        raise CanonicalPathOverrideError(f"absolute path is not canonical: {path!r}")
    return text


def candidate_manifest_relpath(phase: PublicationPhase | str) -> str:
    key = PublicationPhase.coerce(phase).value
    if key.startswith("federal_"):
        return FEDERAL_CANDIDATE_MANIFEST_RELPATH
    return STATE_CANDIDATE_MANIFEST_RELPATH


def dataset_card_relpath(phase: PublicationPhase | str) -> str:
    key = PublicationPhase.coerce(phase).value
    if key.startswith("federal_"):
        return FEDERAL_DATASET_CARD_RELPATH
    return STATE_DATASET_CARD_RELPATH


def main_seal_relpath(phase: PublicationPhase | str) -> Optional[str]:
    contract = phase_requirements(phase)
    path = contract.get("seal_receipt_path")
    return str(path) if path else None


def authoritative_relpaths(phase: PublicationPhase | str) -> tuple[str, ...]:
    contract = phase_requirements(phase)
    paths = [
        RELEASE_POLICY_RELPATH,
        TASKBOARD_RELPATH,
        OBJECTIVES_RELPATH,
        candidate_manifest_relpath(phase),
        dataset_card_relpath(phase),
        *list(contract["required_receipts"]),
    ]
    seal_path = main_seal_relpath(phase)
    if seal_path:
        paths.append(seal_path)
    return tuple(dict.fromkeys(_posix_relpath(item) for item in paths))


def _field_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def _csv_ids(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    return tuple(item for item in re.split(r"[,\s]+", text) if item)


def _secret_values(environ: Mapping[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    for name in TOKEN_ENV_ALLOWLIST:
        item = environ.get(name)
        if isinstance(item, str) and item:
            values.append(item)
    return tuple(values)


def _contains_secret(text: str, secrets: Sequence[str]) -> bool:
    if not text or not secrets:
        return False
    return any(secret and secret in text for secret in secrets)


def _safe_error_text(exc: BaseException, secrets: Sequence[str]) -> str:
    text = str(exc)
    if _contains_secret(text, secrets):
        return type(exc).__name__
    return text


def _assert_secret_free(payload: Any, *, label: str, environ: Mapping[str, str]) -> None:
    reject_credentials_in_payload(payload, label=label, environ=environ)
    dumped = json.dumps(payload, default=str) if not isinstance(payload, str) else payload
    if _contains_secret(dumped, _secret_values(environ)):
        raise CredentialTokenError(f"{label} must not contain credential material")


# ---------------------------------------------------------------------------
# Git / filesystem
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        safe = detail[0] if detail else f"exit {proc.returncode}"
        raise PublicationRuntimeError(f"git {' '.join(args)} failed: {safe[:200]}")
    return proc.stdout


def resolve_repository_root(repository_root: PathLike) -> Path:
    requested = Path(repository_root).expanduser().resolve()
    if not requested.is_dir():
        raise AlternateRepositoryError(
            f"repository root does not exist: {requested.as_posix()}"
        )
    try:
        toplevel = Path(_git(requested, "rev-parse", "--show-toplevel").strip()).resolve()
    except PublicationRuntimeError as exc:
        raise AlternateRepositoryError("repository root is not a git checkout") from exc
    if toplevel != requested:
        raise AlternateRepositoryError(
            "requested root is not the git toplevel; alternate roots cannot authorize"
        )
    return toplevel


def inspect_clean_head(
    repository_root: PathLike,
    *,
    authoritative_paths: Sequence[str] = (),
) -> str:
    """Return the actual 40-hex HEAD after refusing dirty canonical paths."""

    root = resolve_repository_root(repository_root)
    head = _git(root, "rev-parse", "HEAD").strip().casefold()
    if not _GIT_SHA_RE.fullmatch(head):
        raise AlternateRepositoryError("HEAD is not a 40-character lowercase hex commit")
    porcelain = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "-z",
    )
    dirty: list[str] = []
    if porcelain:
        entries = [item for item in porcelain.split("\0") if item]
        # porcelain -z entries are ``XY PATH`` or rename ``XY PATH\\0PATH2``;
        # ``-z`` already split on NUL so each leftover is one status record.
        for entry in entries:
            path = entry[3:] if len(entry) >= 3 else entry
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[1]
            path = path.strip().replace("\\", "/")
            if path:
                dirty.append(path)
    wanted = {_posix_relpath(item) for item in authoritative_paths} if authoritative_paths else set()
    if wanted:
        hits = [
            path
            for path in dirty
            if path in wanted or any(path == item or path.startswith(f"{item}/") for item in wanted)
        ]
        if hits:
            raise DirtyAuthoritativePathError(
                "authoritative paths are dirty: " + ", ".join(sorted(hits)[:12])
            )
    elif dirty:
        raise DirtyAuthoritativePathError(
            "worktree is dirty at HEAD; clean checkout required"
        )
    return require_immutable_revision(head, name="HEAD")


def _resolve_canonical_file(root: Path, relpath: str) -> Path:
    relative = _posix_relpath(relpath)
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CanonicalPathOverrideError(
            f"canonical path escapes repository: {relative}"
        ) from exc
    if path.is_symlink() or (root / relative).is_symlink():
        raise DirtyAuthoritativePathError(
            f"canonical path must not be a symlink: {relative}"
        )
    return path


def read_canonical_bytes(root: Path, relpath: str) -> bytes:
    path = _resolve_canonical_file(root, relpath)
    if not path.is_file():
        raise PublicationRuntimeError(f"canonical file is missing: {relpath}")
    return path.read_bytes()


def read_canonical_text(root: Path, relpath: str) -> str:
    try:
        return read_canonical_bytes(root, relpath).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationRuntimeError(f"canonical file is not UTF-8: {relpath}") from exc


def read_canonical_json(root: Path, relpath: str) -> dict[str, Any]:
    try:
        payload = json.loads(read_canonical_text(root, relpath))
    except json.JSONDecodeError as exc:
        raise PublicationRuntimeError(f"canonical JSON is invalid: {relpath}") from exc
    if not isinstance(payload, dict):
        raise PublicationRuntimeError(f"canonical JSON must be an object: {relpath}")
    return payload


# ---------------------------------------------------------------------------
# Taskboard / objectives
# ---------------------------------------------------------------------------


def _parse_namespaced_records(
    text: str,
    heading_pattern: re.Pattern[str],
    *,
    heading_prefix: str,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith(heading_prefix):
            match = heading_pattern.fullmatch(line)
            if not match:
                current = None
                continue
            current = {"id": match.group(1), "title": match.group(2).strip()}
            records[match.group(1)] = current
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is None or not line.startswith("- "):
            continue
        field = _FIELD_LINE_RE.fullmatch(line)
        if not field:
            continue
        key = _field_key(field.group(1))
        if key and key not in current:
            current[key] = field.group(2).strip()
    return records


def load_task_lineage(root: Path) -> dict[str, Any]:
    tasks = _parse_namespaced_records(
        read_canonical_text(root, TASKBOARD_RELPATH),
        _TASK_HEADING_RE,
        heading_prefix="## LCR-",
    )
    goals = _parse_namespaced_records(
        read_canonical_text(root, OBJECTIVES_RELPATH),
        _GOAL_HEADING_RE,
        heading_prefix="## LCR-G",
    )
    if not tasks:
        raise PublicationRuntimeError("taskboard contains no LCR task records")
    task_statuses = {
        task_id: str(record.get("status") or "").strip().lower()
        for task_id, record in tasks.items()
    }
    task_dependencies = {
        task_id: _csv_ids(record.get("depends_on"))
        for task_id, record in tasks.items()
    }
    task_goal_ids = {
        task_id: str(record.get("goal_id") or "").strip()
        for task_id, record in tasks.items()
        if str(record.get("goal_id") or "").strip()
    }
    goal_parents = {
        goal_id: _csv_ids(record.get("parent")) for goal_id, record in goals.items()
    }
    return {
        "task_statuses": task_statuses,
        "task_dependencies": task_dependencies,
        "task_goal_ids": task_goal_ids,
        "goal_parents": goal_parents,
        "tasks": tasks,
        "goals": goals,
    }


def load_release_policy(root: Path) -> dict[str, Any]:
    policy = read_canonical_json(root, RELEASE_POLICY_RELPATH)
    schema = str(policy.get("schema") or "").strip()
    if schema != "ipfs_datasets_py/legal-corpora-reindex-release-policy@1":
        raise ReceiptSchemaError("release policy schema is unknown")
    return policy


def _same_contract_value(left: Any, right: Any) -> bool:
    if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
        return [str(item) for item in list(left or ())] == [
            str(item) for item in list(right or ())
        ]
    return left == right


def _require_policy_phase_contract(policy: Mapping[str, Any], phase: str) -> None:
    contract = phase_requirements(phase)
    evidence = policy.get("prepublication_evidence_contract")
    if not isinstance(evidence, Mapping):
        raise PublicationRuntimeError("release policy missing prepublication_evidence_contract")
    phases = evidence.get("phase_requirements")
    if not isinstance(phases, Mapping) or phase not in phases:
        raise PublicationRuntimeError(f"release policy missing phase {phase}")
    observed = phases[phase]
    if not isinstance(observed, Mapping):
        raise PublicationRuntimeError(f"release policy phase {phase} is not an object")
    for key in (
        "dataset_repo_id",
        "authorized_operation",
        "required_task_ids",
        "required_receipts",
        "prepublication_seal_required",
    ):
        if not _same_contract_value(observed.get(key), contract.get(key)):
            raise PublicationRuntimeError(
                f"release policy {phase}.{key} drifts from the sealed gate contract"
            )
    baselines = policy.get("baseline_revisions")
    if not isinstance(baselines, Mapping):
        raise PublicationRuntimeError("release policy missing baseline_revisions")
    expected_pin = contract["previous_public_pin"]
    observed_pin = baselines.get(contract["dataset_repo_id"])
    if observed_pin != expected_pin:
        raise PublicationRuntimeError(
            "release policy baseline pin drifts from the sealed gate contract"
        )


# ---------------------------------------------------------------------------
# Receipts / manifests / seals
# ---------------------------------------------------------------------------


def _declared_digest(payload: Mapping[str, Any], *names: str) -> Optional[str]:
    for name in names:
        value = payload.get(name)
        if value is None or value == "":
            continue
        text = str(value).strip().casefold()
        if text.startswith("sha256:"):
            text = text[len("sha256:") :]
        if not _SHA256_RE.fullmatch(text):
            raise IndependentDigestError(f"{name} is not a 64-character hex digest")
        return text
    return None


def verify_independent_digests(
    *,
    relpath: str,
    raw: bytes,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    raw_digest = raw_file_digest(raw)
    canonical_digest = canonical_no_self_field_digest(payload)
    declared_canonical = _declared_digest(
        payload, "canonical_digest", "content_digest", "receipt_sha256", "digest"
    )
    if declared_canonical is None:
        raise IndependentDigestError(
            f"{relpath} is missing an independently verifiable digest"
        )
    if declared_canonical != canonical_digest:
        raise IndependentDigestError(
            f"{relpath} declared digest does not match canonical no-self-field recompute"
        )
    declared_raw = _declared_digest(payload, "raw_sha256")
    if declared_raw is not None and declared_raw != raw_digest:
        raise IndependentDigestError(
            f"{relpath} declared raw digest does not match file bytes"
        )
    return {
        "raw_sha256": raw_digest,
        "canonical_digest": canonical_digest,
        "content_digest": canonical_digest,
    }


def _require_receipt_schema(payload: Mapping[str, Any], relpath: str) -> str:
    schema = str(payload.get("schema") or "").strip()
    if not schema:
        raise ReceiptSchemaError(f"{relpath} is missing a receipt schema")
    if schema not in ALLOWED_RECEIPT_SCHEMAS:
        raise ReceiptSchemaError(f"{relpath} has unknown receipt schema {schema!r}")
    return schema


def _require_receipt_status(payload: Mapping[str, Any], relpath: str) -> str:
    if "status" not in payload:
        raise ReceiptStatusError(f"{relpath} is missing status")
    status = str(payload.get("status") or "").strip().lower()
    if not status:
        raise ReceiptStatusError(f"{relpath} is missing status")
    return status


def load_receipt(root: Path, relpath: str) -> dict[str, Any]:
    raw = read_canonical_bytes(root, relpath)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise PublicationRuntimeError(f"receipt must be a JSON object: {relpath}")
    _require_receipt_schema(payload, relpath)
    status = _require_receipt_status(payload, relpath)
    digests = verify_independent_digests(relpath=relpath, raw=raw, payload=payload)
    receipt = dict(payload)
    receipt["path"] = relpath
    receipt["status"] = status
    receipt["content_digest"] = digests["content_digest"]
    receipt["canonical_digest"] = digests["canonical_digest"]
    receipt["raw_sha256"] = digests["raw_sha256"]
    receipt.setdefault("fixture_only", False)
    receipt.setdefault("dirty", False)
    return receipt


def parse_utc_z(value: Any, *, name: str = "sealed_at") -> datetime:
    text = str(value or "").strip()
    if not text:
        raise SealTimeError(f"{name} is missing")
    if _OFFSET_TIME_RE.search(text) or text.endswith("+00:00") or text.endswith("-00:00"):
        raise SealTimeError(f"{name} must be strict UTC-Z, not an offset timestamp")
    match = _UTC_Z_RE.fullmatch(text)
    if not match:
        raise SealTimeError(f"{name} must be YYYY-MM-DDTHH:MM:SSZ")
    parsed = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return parsed


def load_main_seal(
    root: Path,
    phase: str,
    *,
    mutation_start: datetime,
    head: str,
    manifest_digest: str,
    dataset_repo_id: str,
) -> Optional[dict[str, Any]]:
    if not prepublication_seal_required(phase):
        return None
    relpath = main_seal_relpath(phase)
    if not relpath:
        raise SealTimeError(f"{phase} is missing a sealed seal path")
    raw = read_canonical_bytes(root, relpath)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise SealTimeError("prepublication seal must be a JSON object")
    _require_receipt_schema(payload, relpath)
    _require_receipt_status(payload, relpath)
    digests = verify_independent_digests(relpath=relpath, raw=raw, payload=payload)
    if payload.get("present") is not True:
        raise SealTimeError("main mutation requires present=true prepublication seal")
    sealed_at = parse_utc_z(payload.get("sealed_at") or payload.get("seal_time"))
    now = datetime.now(timezone.utc)
    if sealed_at > now:
        raise SealTimeError("main mutation refuses future-dated prepublication seal")
    if sealed_at >= mutation_start:
        raise SealTimeError("main mutation refuses post-mutation prepublication seal")
    bound_manifest = payload.get("final_manifest_digest") or payload.get("manifest_digest")
    if not bound_manifest:
        raise SealTimeError("prepublication seal is missing final_manifest_digest")
    if normalize_sha256(bound_manifest, name="seal.final_manifest_digest") != manifest_digest:
        raise SealTimeError("prepublication seal does not bind the candidate manifest digest")
    bound_head = str(payload.get("head") or payload.get("git_head") or "").strip().casefold()
    if bound_head and require_immutable_revision(bound_head, name="seal.head") != head:
        raise SealTimeError("prepublication seal HEAD does not match the actual clean HEAD")
    bound_repo = str(
        payload.get("dataset_repo_id") or payload.get("target_dataset_repo_id") or ""
    ).strip()
    if bound_repo and bound_repo != dataset_repo_id:
        raise SealTimeError("prepublication seal target does not match the mutation dataset")
    if payload.get("created_after_mutation") is True or payload.get("post_hoc") is True:
        raise SealTimeError("main mutation refuses post-hoc prepublication seal")
    staging = payload.get("staging_revision")
    if not staging:
        raise SealTimeError("main mutation seal is missing staging_revision")
    seal = dict(payload)
    seal.update(digests)
    seal["path"] = relpath
    seal["present"] = True
    seal["timing"] = "before_mutation"
    seal["sealed_at"] = sealed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    seal["staging_revision"] = require_immutable_revision(
        staging, name="seal.staging_revision"
    )
    return seal


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def obtain_token(environ: Mapping[str, str]) -> tuple[str, str]:
    found: list[tuple[str, str]] = []
    for name in TOKEN_ENV_ALLOWLIST:
        value = environ.get(name)
        if isinstance(value, str) and value.strip():
            found.append((name, value))
    if not found:
        raise CredentialTokenError(
            "allowlisted credential environment variable is missing or empty"
        )
    names = {name for name, _ in found}
    values = {value for _, value in found}
    if len(values) > 1:
        raise CredentialTokenError("allowlisted credential environment variables disagree")
    name, token = found[0]
    if any(token == other and other != name for other in names):
        pass
    if not token.strip():
        raise CredentialTokenError("allowlisted credential environment variable is empty")
    return name, token


def verify_write_authority(
    *,
    token: str,
    dataset_repo_id: str,
    principal_probe: PrincipalProbe,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    if principal_probe is None:
        raise PrincipalAuthorityError("read-only principal probe is required")
    try:
        projection = principal_probe(token, dataset_repo_id)
    except PublicationGateError:
        raise
    except Exception as exc:
        raise PrincipalAuthorityError(
            "principal probe failed: " + _safe_error_text(exc, (token, *_secret_values(environ)))
        ) from exc
    if not isinstance(projection, Mapping):
        raise PrincipalAuthorityError("principal probe must return a mapping")
    _assert_secret_free(dict(projection), label="principal_probe", environ=environ)
    if _contains_secret(json.dumps(dict(projection), default=str), (token,)):
        raise PrincipalAuthorityError("principal probe leaked credential material")
    principal = str(projection.get("principal") or projection.get("name") or "").strip()
    if not principal:
        raise PrincipalAuthorityError("principal probe did not return a principal")
    expected_scope = credentials_scope_for(dataset_repo_id)
    write_ok = projection.get("has_write_access")
    write_targets = {
        str(item).strip()
        for item in (
            projection.get("write_targets")
            or projection.get("dataset_repo_ids")
            or ()
        )
        if str(item).strip()
    }
    scopes = {
        str(item).strip()
        for item in (projection.get("scopes") or projection.get("write_scopes") or ())
        if str(item).strip()
    }
    target = str(projection.get("dataset_repo_id") or "").strip()
    if target and target != dataset_repo_id:
        raise PrincipalAuthorityError("principal is target-mismatched for the mutation dataset")
    if write_targets and dataset_repo_id not in write_targets:
        raise PrincipalAuthorityError("principal write targets omit the exact mutation dataset")
    if scopes and expected_scope not in scopes and dataset_repo_id not in scopes:
        raise PrincipalAuthorityError("principal scopes omit the exact mutation dataset")
    if write_ok is False:
        raise PrincipalAuthorityError("principal lacks write authority for the exact target")
    if write_ok is not True and dataset_repo_id not in write_targets and expected_scope not in scopes:
        raise PrincipalAuthorityError("principal write authority for the exact target was not proven")
    identity = str(projection.get("identity") or "").strip() or f"env:{dataset_repo_id}"
    if dataset_repo_id not in identity and expected_scope not in identity:
        identity = f"env:{dataset_repo_id}"
    return {
        "principal": principal,
        "identity": identity,
        "credentials_scope": expected_scope,
        "dataset_repo_id": dataset_repo_id,
        "token_env": next(
            (name for name in TOKEN_ENV_ALLOWLIST if environ.get(name) == token),
            TOKEN_ENV_ALLOWLIST[0],
        ),
    }


# ---------------------------------------------------------------------------
# Snapshot / request construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalPublicationRequest:
    """Non-authoritative caller envelope. Canonical paths and HEAD are derived."""

    phase: str
    repository_root: Path
    authorize_mutation: bool = True
    environ: Mapping[str, str] | None = None
    principal_probe: PrincipalProbe | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", PublicationPhase.coerce(self.phase).value)
        object.__setattr__(
            self, "repository_root", Path(self.repository_root).expanduser()
        )
        if self.environ is not None and not isinstance(self.environ, Mapping):
            raise PublicationRuntimeError("environ must be a mapping")
        if self.principal_probe is not None and not callable(self.principal_probe):
            raise PublicationRuntimeError("principal_probe must be callable")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalPublicationRequest":
        if not isinstance(value, Mapping):
            raise PublicationRuntimeError("canonical publication request must be a mapping")
        extras = set(value) & AUTHORITATIVE_OVERRIDE_KEYS
        commit_keys = extras & {
            "branch",
            "claimed_commit",
            "claimed_head",
            "commit",
            "current_commit",
            "git_ref",
            "ref",
        }
        if commit_keys:
            raise CallerCommitError(
                "caller-selected commits cannot authorize: "
                + ", ".join(sorted(commit_keys))
            )
        if extras:
            raise CanonicalPathOverrideError(
                "authoritative caller overrides are rejected: "
                + ", ".join(sorted(extras))
            )
        return cls(
            phase=value.get("phase", ""),
            repository_root=Path(str(value.get("repository_root") or value.get("repo_root") or "")),
            authorize_mutation=bool(value.get("authorize_mutation", True)),
            environ=value.get("environ"),
            principal_probe=value.get("principal_probe"),
        )


def _control_digests(root: Path, phase: str) -> dict[str, str]:
    digests: dict[str, str] = {}
    for relpath in authoritative_relpaths(phase):
        path = _resolve_canonical_file(root, relpath)
        if path.is_file():
            digests[relpath] = raw_file_digest(path.read_bytes())
    return digests


def capture_canonical_snapshot(
    request: CanonicalPublicationRequest,
    *,
    mutation_start: Optional[datetime] = None,
) -> dict[str, Any]:
    environ = dict(request.environ or {})
    start = mutation_start or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    root = resolve_repository_root(request.repository_root)
    paths = authoritative_relpaths(request.phase)
    head = inspect_clean_head(root, authoritative_paths=paths)
    policy = load_release_policy(root)
    _require_policy_phase_contract(policy, request.phase)
    lineage = load_task_lineage(root)
    contract = phase_requirements(request.phase)
    receipts: dict[str, dict[str, Any]] = {}
    expected: dict[str, str] = {}
    for relpath in contract["required_receipts"]:
        receipt = load_receipt(root, relpath)
        receipts[relpath] = receipt
        expected[relpath] = receipt["content_digest"]

    manifest_relpath = candidate_manifest_relpath(request.phase)
    if manifest_relpath not in receipts:
        receipts[manifest_relpath] = load_receipt(root, manifest_relpath)
        expected[manifest_relpath] = receipts[manifest_relpath]["content_digest"]
    manifest = dict(receipts[manifest_relpath])
    if manifest.get("schema") != MANIFEST_SCHEMA_V1:
        raise ManifestBindingError("candidate manifest schema is not bound")
    rights = receipts.get(RIGHTS_RECEIPT_RELPATH)
    if not isinstance(rights, Mapping):
        raise ManifestBindingError("source-rights receipt is missing from canonical paths")
    bound_rights = str(
        manifest.get("source_rights_receipt_digest")
        or manifest.get("source_rights_compliance_digest")
        or ""
    ).strip()
    if not bound_rights:
        raise ManifestBindingError("candidate manifest does not bind the source-rights receipt")
    if normalize_sha256(bound_rights, name="manifest.source_rights_receipt_digest") != rights[
        "content_digest"
    ]:
        raise ManifestBindingError("candidate manifest source-rights digest does not match receipt")
    card_text = read_canonical_text(root, dataset_card_relpath(request.phase))
    if rights["content_digest"] not in card_text and rights["content_digest"][:16] not in card_text:
        raise ManifestBindingError("dataset card does not bind the source-rights receipt digest")

    on_disk_manifest = read_canonical_json(root, manifest_relpath)
    recomputed_manifest = canonical_no_self_field_digest(on_disk_manifest)
    declared_manifest = str(on_disk_manifest.get("final_manifest_digest") or "").strip()
    if declared_manifest:
        if normalize_sha256(declared_manifest, name="final_manifest_digest") != recomputed_manifest:
            raise IndependentDigestError(
                "candidate final_manifest_digest does not match no-self-field recompute"
            )
    final_manifest_digest = recomputed_manifest

    dataset_repo_id = contract["dataset_repo_id"]
    if dataset_repo_id not in AUTHORIZED_DATASET_REPO_IDS:
        raise PublicationRuntimeError("phase dataset is not an authorized legal-corpora target")

    token_name, token = obtain_token(environ)
    if request.principal_probe is None:
        raise PrincipalAuthorityError("read-only principal probe is required")
    identity = verify_write_authority(
        token=token,
        dataset_repo_id=dataset_repo_id,
        principal_probe=request.principal_probe,
        environ=environ,
    )

    seal = load_main_seal(
        root,
        request.phase,
        mutation_start=start,
        head=head,
        manifest_digest=final_manifest_digest,
        dataset_repo_id=dataset_repo_id,
    )
    staging_revision = None
    if seal is not None:
        staging_revision = seal.get("staging_revision")
    elif request.phase.endswith("_main"):
        raise SealTimeError("main mutation requires a canonical prepublication seal")

    snapshot = {
        "head": head,
        "phase": request.phase,
        "repository_root": root.as_posix(),
        "mutation_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_policy_digest": raw_file_digest(
            read_canonical_bytes(root, RELEASE_POLICY_RELPATH)
        ),
        "control_digests": _control_digests(root, request.phase),
        "task_statuses": lineage["task_statuses"],
        "task_dependencies": lineage["task_dependencies"],
        "task_goal_ids": lineage["task_goal_ids"],
        "goal_parents": lineage["goal_parents"],
        "receipts": receipts,
        "expected_receipt_digests": expected,
        "candidate_manifest": {
            key: value
            for key, value in manifest.items()
            if key not in SELF_DIGEST_FIELDS
        },
        "dataset_card": card_text,
        "final_manifest_digest": final_manifest_digest,
        "dataset_repo_id": dataset_repo_id,
        "operation": contract["authorized_operation"],
        "previous_public_pin": contract["previous_public_pin"],
        "prepublication_seal": seal,
        "staging_revision": staging_revision,
        "credential_identity": identity["identity"],
        "credentials_scope": identity["credentials_scope"],
        "principal": identity["principal"],
        "token_env": token_name,
        "authorize_mutation": bool(request.authorize_mutation),
    }
    _assert_secret_free(snapshot, label="canonical_snapshot", environ=environ)
    return snapshot


def build_gate_request(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "phase": snapshot["phase"],
        "operation": snapshot["operation"],
        "dataset_repo_id": snapshot["dataset_repo_id"],
        "final_manifest_digest": snapshot["final_manifest_digest"],
        "previous_public_pin": snapshot["previous_public_pin"],
        "task_statuses": dict(snapshot["task_statuses"]),
        "task_dependencies": {
            key: list(value) for key, value in dict(snapshot["task_dependencies"]).items()
        },
        "task_goal_ids": dict(snapshot["task_goal_ids"]),
        "goal_parents": {
            key: list(value) for key, value in dict(snapshot["goal_parents"]).items()
        },
        "receipts": {key: dict(value) for key, value in dict(snapshot["receipts"]).items()},
        "expected_receipt_digests": dict(snapshot["expected_receipt_digests"]),
        "credentials_environment_only": True,
        "credentials_scope": snapshot["credentials_scope"],
        "credential_identity": snapshot["credential_identity"],
        "secret_redacted": True,
        "authorize_mutation": bool(snapshot["authorize_mutation"]),
        "evidence_is_dirty": False,
        "fixture_only_evidence": False,
        "current_commit": snapshot["head"],
        "payload": {
            "release_mode": "additive",
            "credentials_environment_only": True,
            "secret_redacted": True,
            "candidate_manifest": dict(snapshot["candidate_manifest"]),
            "dataset_card": snapshot["dataset_card"],
            "canonical_head": snapshot["head"],
            "runtime_task_id": TASK_ID,
            "runtime_goal_id": GOAL_ID,
            "gate_task_id": PREDECESSOR_GATE_TASK_ID,
            "source_rights_task_id": PREDECESSOR_RIGHTS_TASK_ID,
            "control_digests": dict(snapshot["control_digests"]),
            "principal": snapshot["principal"],
            "token_env": snapshot["token_env"],
            "mutation_start": snapshot["mutation_start"],
        },
        "argv": [
            "publish-legal-corpora",
            "--phase",
            str(snapshot["phase"]),
            "--authorize-mutation",
        ],
    }
    if snapshot.get("staging_revision"):
        payload["staging_revision"] = snapshot["staging_revision"]
    if snapshot.get("prepublication_seal") is not None:
        payload["prepublication_seal"] = dict(snapshot["prepublication_seal"])
    return payload


def _snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    material = {
        "head": snapshot.get("head"),
        "control_digests": snapshot.get("control_digests"),
        "expected_receipt_digests": snapshot.get("expected_receipt_digests"),
        "final_manifest_digest": snapshot.get("final_manifest_digest"),
        "task_statuses": snapshot.get("task_statuses"),
    }
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _denied_decision(
    *,
    phase: str,
    reason_code: str,
    message: str,
    environ: Mapping[str, str],
    extra: Optional[Mapping[str, Any]] = None,
) -> PublicationGateDecision:
    contract = None
    repo = STATE_DATASET_REPO_ID
    operation = "unknown"
    pin = str(BASELINE_REVISIONS[STATE_DATASET_REPO_ID])
    digest = "0" * 64
    try:
        coerced = PublicationPhase.coerce(phase).value
        contract = phase_requirements(coerced)
        repo = contract["dataset_repo_id"]
        operation = contract["authorized_operation"]
        pin = contract["previous_public_pin"]
        phase = coerced
    except PublicationGateError:
        pass
    details = {
        "task_id": TASK_ID,
        "gate_task_id": PREDECESSOR_GATE_TASK_ID,
        "producer": PRODUCER,
        "schema_version": SCHEMA_VERSION,
        "error": message,
        **dict(extra or {}),
    }
    decision = PublicationGateDecision(
        authorized=False,
        phase=phase,
        operation=operation,
        dataset_repo_id=repo if repo in AUTHORIZED_DATASET_REPO_IDS else STATE_DATASET_REPO_ID,
        final_manifest_digest=digest,
        previous_public_pin=pin,
        reason_codes=(reason_code,),
        passed_gates=(),
        required_gates=REQUIRED_PUBLICATION_GATES,
        message=message,
        details=details,
        network_mutation_permitted=False,
    )
    _assert_secret_free(decision.to_dict(), label="publication_runtime_decision", environ=environ)
    return decision


def evaluate_canonical_publication(
    request: CanonicalPublicationRequest | Mapping[str, Any],
    *,
    mutation_start: Optional[datetime] = None,
) -> PublicationGateDecision:
    """Load canonical evidence and evaluate the LCR-074/LCR-083 gate."""

    environ: dict[str, str] = {}
    phase = "unknown"
    try:
        req = (
            request
            if isinstance(request, CanonicalPublicationRequest)
            else CanonicalPublicationRequest.from_mapping(request)
        )
        phase = req.phase
        environ = dict(req.environ or {})
        start = mutation_start or datetime.now(timezone.utc)
        snapshot = capture_canonical_snapshot(req, mutation_start=start)
        gate_request = build_gate_request(snapshot)
        decision = evaluate_publication_gate(gate_request, environ=environ)
        details = dict(decision.details)
        details.update(
            {
                "runtime_task_id": TASK_ID,
                "runtime_goal_id": GOAL_ID,
                "gate_task_id": PREDECESSOR_GATE_TASK_ID,
                "source_rights_task_id": PREDECESSOR_RIGHTS_TASK_ID,
                "head": snapshot["head"],
                "token_env": snapshot["token_env"],
                "principal": snapshot["principal"],
                "mutation_start": snapshot["mutation_start"],
                "control_digest_count": len(snapshot["control_digests"]),
                "snapshot_fingerprint": _snapshot_fingerprint(snapshot),
                "source_rights_binding_required": True,
                "required_gates": list(REQUIRED_PUBLICATION_GATES),
            }
        )
        bound = PublicationGateDecision(
            authorized=decision.authorized,
            phase=decision.phase,
            operation=decision.operation,
            dataset_repo_id=decision.dataset_repo_id,
            final_manifest_digest=decision.final_manifest_digest,
            previous_public_pin=decision.previous_public_pin,
            reason_codes=decision.reason_codes,
            passed_gates=decision.passed_gates,
            required_gates=REQUIRED_PUBLICATION_GATES,
            message=decision.message,
            details=details,
            network_mutation_permitted=decision.network_mutation_permitted,
        )
        _assert_secret_free(bound.to_dict(), label="publication_runtime_decision", environ=environ)
        return bound
    except PublicationGateError as exc:
        code = f"runtime.{getattr(exc, 'code', 'publication_runtime_error')}"
        return _denied_decision(
            phase=phase,
            reason_code=code,
            message=_safe_error_text(exc, _secret_values(environ)),
            environ=environ,
        )


def require_canonical_publication(
    request: CanonicalPublicationRequest | Mapping[str, Any],
    *,
    mutation_start: Optional[datetime] = None,
) -> PublicationGateDecision:
    decision = evaluate_canonical_publication(request, mutation_start=mutation_start)
    return decision.require_authorized()


def authorize_and_mutate_canonical(
    request: CanonicalPublicationRequest | Mapping[str, Any],
    upload_callback: Callable[[PublicationGateDecision], T],
) -> T:
    """Callback-owning adapter for all four mutation phases.

    Revalidates canonical evidence immediately before invoking *upload_callback*.
    The callback is never invoked on any denial path and runs exactly once after
    a fully canonical authorized request.
    """

    environ: dict[str, str] = {}
    phase = "unknown"
    try:
        req = (
            request
            if isinstance(request, CanonicalPublicationRequest)
            else CanonicalPublicationRequest.from_mapping(request)
        )
        phase = req.phase
        environ = dict(req.environ or {})
    except PublicationGateError as exc:
        denied = _denied_decision(
            phase=phase,
            reason_code=f"runtime.{getattr(exc, 'code', 'publication_runtime_error')}",
            message=_safe_error_text(exc, _secret_values(environ)),
            environ=environ,
        )
        raise PublicationGateDeniedError(
            denied.message,
            reason_codes=denied.reason_codes,
            decision=denied,
        ) from exc
    mutation_start = datetime.now(timezone.utc)
    try:
        first = capture_canonical_snapshot(req, mutation_start=mutation_start)
        gate_request = build_gate_request(first)
        decision = evaluate_publication_gate(gate_request, environ=environ)
    except PublicationGateError as exc:
        denied = _denied_decision(
            phase=req.phase,
            reason_code=f"runtime.{getattr(exc, 'code', 'publication_runtime_error')}",
            message=_safe_error_text(exc, _secret_values(environ)),
            environ=environ,
        )
        raise PublicationGateDeniedError(
            denied.message,
            reason_codes=denied.reason_codes,
            decision=denied,
        ) from exc
    if not decision.authorized:
        raise PublicationGateDeniedError(
            decision.message or "canonical publication denied",
            reason_codes=decision.reason_codes,
            decision=decision,
        )
    try:
        second = capture_canonical_snapshot(req, mutation_start=mutation_start)
    except PublicationGateError as exc:
        race = _denied_decision(
            phase=req.phase,
            reason_code="runtime.evidence_race",
            message="canonical evidence changed between authorization and mutation",
            environ=environ,
            extra={"head_before": first.get("head")},
        )
        raise PublicationGateDeniedError(
            race.message,
            reason_codes=race.reason_codes,
            decision=race,
        ) from exc
    if _snapshot_fingerprint(first) != _snapshot_fingerprint(second):
        race = _denied_decision(
            phase=req.phase,
            reason_code="runtime.evidence_race",
            message="canonical evidence changed between authorization and mutation",
            environ=environ,
            extra={"head_before": first["head"], "head_after": second["head"]},
        )
        raise PublicationGateDeniedError(
            race.message,
            reason_codes=race.reason_codes,
            decision=race,
        )
    details = dict(decision.details)
    details.update(
        {
            "runtime_task_id": TASK_ID,
            "head": first["head"],
            "snapshot_fingerprint": _snapshot_fingerprint(first),
            "revalidated_before_callback": True,
            "source_rights_binding_required": True,
        }
    )
    bound = PublicationGateDecision(
        authorized=True,
        phase=decision.phase,
        operation=decision.operation,
        dataset_repo_id=decision.dataset_repo_id,
        final_manifest_digest=decision.final_manifest_digest,
        previous_public_pin=decision.previous_public_pin,
        reason_codes=(),
        passed_gates=decision.passed_gates,
        required_gates=REQUIRED_PUBLICATION_GATES,
        message=decision.message,
        details=details,
        network_mutation_permitted=True,
    )
    _assert_secret_free(bound.to_dict(), label="publication_runtime_decision", environ=environ)
    if not bound.network_mutation_permitted:
        raise PublicationGateDeniedError(
            "network mutation not permitted",
            reason_codes=("network_mutation.denied",),
            decision=bound,
        )
    return upload_callback(bound)


__all__ = [
    "ALLOWED_RECEIPT_SCHEMAS",
    "AUTHORITATIVE_OVERRIDE_KEYS",
    "CANONICAL_PATHS",
    "GOAL_ID",
    "PREDECESSOR_GATE_TASK_ID",
    "PREDECESSOR_RIGHTS_TASK_ID",
    "PROGRAM_ID",
    "PRODUCER",
    "RUNTIME_SCHEMA",
    "SCHEMA_VERSION",
    "TASK_ID",
    "TOKEN_ENV_ALLOWLIST",
    "AlternateRepositoryError",
    "CanonicalPathOverrideError",
    "CanonicalPublicationRequest",
    "CallerCommitError",
    "CredentialTokenError",
    "DirtyAuthoritativePathError",
    "EvidenceRaceError",
    "IndependentDigestError",
    "ManifestBindingError",
    "PrincipalAuthorityError",
    "PublicationRuntimeError",
    "ReceiptSchemaError",
    "ReceiptStatusError",
    "SealTimeError",
    "authoritative_relpaths",
    "authorize_and_mutate_canonical",
    "build_gate_request",
    "canonical_no_self_field_digest",
    "capture_canonical_snapshot",
    "evaluate_canonical_publication",
    "inspect_clean_head",
    "load_release_policy",
    "load_task_lineage",
    "obtain_token",
    "parse_utc_z",
    "raw_file_digest",
    "require_canonical_publication",
    "verify_write_authority",
]
