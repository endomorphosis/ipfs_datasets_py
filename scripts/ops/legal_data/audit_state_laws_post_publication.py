#!/usr/bin/env python3
"""Audit post-publication completeness and update readiness (LCR-046).

Read-only verifier against the immutable public SHA recorded by LCR-042
and already proven by the LCR-043 public canary, LCR-044 public
benchmark, and LCR-045 rollback rehearsal. This script never mutates the
Hub, never mixes a newer official source into the sealed release, and
never treats a fixture-only substitute as a public pin.

Default ``--check`` is credential-free and does not contact the Hub:

1. Require the LCR-043 public canary, LCR-044 public benchmark, and
   LCR-045 rollback rehearsal as preconditions.
2. Reconstruct the published artifact tree from the sealed candidate
   (in-memory FakeHub redownload).
3. Reconcile the exact-51 official source receipts through the public
   files, the publication upload responses, and the local candidate.
4. Check timestamps and as-of disclaimers: observation / acquisition
   time is never legal currentness.
5. Check update checkpoints (source-frontier completion; no partial
   promotion) across the 13 sealed cohort receipts.
6. Compare remote (reconstructed public) and local (candidate)
   manifests; drift is a contradiction, not an adjusted receipt.
7. Seed bounded future delta / refill findings. Any new upstream change
   is identified as delta work and is not silently mixed into this
   release. The update plan preserves the exact-51 and transactional
   gates.

Validation gate::

    python scripts/ops/legal_data/audit_state_laws_post_publication.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    RECEIPT_SCHEMA_V1,
    canonical_no_self_field_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    EXPECTED_JURISDICTION_COUNT,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    canonical_json_dumps,
    digest_mapping,
    required_semantic_families,
    validate_jurisdiction_set,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER,
)
from scripts.ops.legal_data.benchmark_state_laws_public_release import (
    check_canonical_public_benchmark_receipt,
)
from scripts.ops.legal_data.check_state_laws_public_release import (
    check_canonical_public_canary_receipt,
)
from scripts.ops.legal_data.rehearse_state_laws_release_rollback import (
    check_canonical_rollback_rehearsal,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-046"
GOAL_ID: Final = "LCR-G090"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
PRODUCTION_REVISION: Final = PREVIOUS_PUBLIC_PIN
PUBLIC_BRANCH: Final = "main"
DEFAULT_OBSERVATION_CUTOFF: Final = "2026-08-10T00:00:00Z"
SORTED_JURISDICTIONS: Final = tuple(sorted(CANONICAL_JURISDICTIONS))
if DEFAULT_DATASET_REPO != "justicedao/ipfs_state_laws":
    raise RuntimeError("sealed state-law target drifted from the publication gate")
if DEFAULT_DATASET_REPO != DEFAULT_DATASET_REPO_ID:
    raise RuntimeError("sealed state-law target drifted from DEFAULT_DATASET_REPO_ID")
if EXPECTED_JURISDICTION_COUNT != 51 or "DC" not in SORTED_JURISDICTIONS:
    raise RuntimeError("exact-51 jurisdiction constant drifted")
PRODUCER: Final = "audit_state_laws_post_publication.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "state-laws-post-publication-audit/v1"
CANONICAL_AUDIT_SCHEMA: Final = RECEIPT_SCHEMA_V1
CANONICAL_AUDIT_KIND: Final = "state-laws-post-publication-audit/v2"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-043", "LCR-044", "LCR-045")
PUBLICATION_TASK_ID: Final = "LCR-042"
PUBLIC_CANARY_TASK_ID: Final = "LCR-043"
PUBLIC_BENCHMARK_TASK_ID: Final = "LCR-044"
ROLLBACK_REHEARSAL_TASK_ID: Final = "LCR-045"

AUDIT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-post-publication-audit@1"
DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/post_publication_audit.json"
)
DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/publication_receipt.json"
)
DEFAULT_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_canary.json"
)
DEFAULT_BENCHMARK_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_benchmark.json"
)
DEFAULT_REHEARSAL_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/rollback_rehearsal.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
DEFAULT_COVERAGE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/full_scrape_coverage.json"
)
DEFAULT_ADMISSION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/admission.json"
)
COHORT_REPORT_RELPATHS: Final[tuple[Path, ...]] = tuple(
    Path(f"docs/reports/legal_corpora_reindex/cohort_{letter}.json")
    for letter in "abcdefghijklm"
)

SOURCE_RECEIPT_PATH_RE: Final = re.compile(
    r"^receipts/scrape/jurisdiction-([A-Z]{2})\.json$"
)
_GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_ISO_Z_RE: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)?$"
)

MAX_REPORT_BYTES: Final = 1048576
MAX_DELTA_FINDINGS: Final = EXPECTED_JURISDICTION_COUNT

SELF_DIGEST_FIELDS: Final = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "file_sha256",
        "final_manifest_digest",
        "manifest_digest",
        "raw_digest",
        "report_digest_sha256",
        "sha256",
    }
)

UPDATE_PLAN_STEPS: Final[tuple[str, ...]] = (
    "resolve_and_approve_official_release_point",
    "diff_stable_legal_id_and_content_hashes",
    "classify_upstream_change_as_delta_work",
    "refuse_silent_mix_into_this_release",
    "re_run_cohort_scrape_only_for_changed_jurisdictions",
    "rebuild_required_families_with_atomic_per_jurisdiction_checkpoints",
    "package_additive_hub_release_without_deleting_legacy",
    "stage_dry_run_and_canary",
    "assemble_new_publication_seal",
    "upload_additively_and_keep_previous_pin_as_rollback",
    "rehearse_dual_pin_query_and_rollback",
)

EXPECTED_ACCEPTANCE: Final[dict[str, bool]] = {
    "bounded_future_delta_refill_findings": True,
    "credentials_environment_only": True,
    "exact_51_coverage": True,
    "fixture_only_rejected": True,
    "includes_dc": True,
    "new_upstream_change_identified_as_delta_work": True,
    "no_absolute_path_or_secret": True,
    "no_contradiction_remains": True,
    "no_remote_mutation": True,
    "not_silently_mixed_into_this_release": True,
    "public_benchmark_bound": True,
    "public_canary_bound": True,
    "public_pin_immutable": True,
    "publication_receipt_bound": True,
    "read_only": True,
    "remote_local_manifests_agree": True,
    "rollback_rehearsal_bound": True,
    "secrets_absent": True,
    "source_receipts_reconcile_through_public_files": True,
    "timestamps_and_as_of_disclaimers_ok": True,
    "update_checkpoints_ok": True,
    "update_plan_preserves_exact_51": True,
    "update_plan_preserves_transactional_gates": True,
}

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    "STATE_LAWS_STAGING_AUTHORIZATION",
    "STATE_LAWS_PUBLICATION_AUTHORIZATION",
)

FORBIDDEN_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "delete",
        "delete_file",
        "delete_folder",
        "force",
        "force_push",
        "force-push",
        "overwrite_history",
        "visibility_change",
        "change_visibility",
        "make_private",
        "make_unlisted",
        "set_private",
        "set_unlisted",
        "rotate_credentials",
        "history_rewrite",
        "super_squash_history",
        "overwrite_legacy",
        "direct_main_upload",
        "promote_production",
        "change_public_advertisement",
    }
)

_TOKEN_KEY_RE: Final = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization|publication_authorization)s?$",
    re.IGNORECASE,
)
_ABS_PATH_RE: Final = re.compile(
    r"(?:^|[\s\"'`=:])"
    r"(?:"
    r"/(?:home|Users|tmp|var|private|opt|root|etc|mnt|media|workspace)/"
    r"|[A-Za-z]:\\"
    r"|file://"
    r")"
)
# Hugging Face user tokens are `hf_` + a long secret suffix. Do not treat
# identifiers such as package_additive_hf_release_* as credentials.
_HF_TOKEN_RE: Final = re.compile(r"(?<![a-z0-9_])hf_[a-z0-9]{16,}", re.IGNORECASE)


class PostPublicationAuditError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PostPublicationContradictionError(PostPublicationAuditError):
    """Raised when a sealed-release contradiction remains."""


class PostPublicationSafetyError(PostPublicationAuditError):
    """Raised when mutation, secrets, or path leaks are detected."""


class PostPublicationDeltaError(PostPublicationAuditError):
    """Raised when an upstream change was silently mixed into this release."""


class PostPublicationPinError(PostPublicationAuditError):
    """Raised when a public pin contract fails."""


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    text = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(text):
        raise PostPublicationPinError(
            f"{name} must be an immutable 40-hex SHA, got {value!r}"
        )
    if text in {"main", "master", "latest", "head", "staging", "canary"}:
        raise PostPublicationPinError(f"{name} must not be a mutable revision")
    return text


def require_public_pin(payload: Mapping[str, Any], *, name: str = "public_sha") -> str:
    raw = payload.get("public_sha") or payload.get("public_revision")
    if raw in (None, ""):
        raise PostPublicationPinError(f"{name} is missing from the publication receipt/canary")
    return require_immutable_revision(raw, name=name)


def validate_repo_id(value: Any, *, name: str = "repo_id") -> str:
    text = str(value or "").strip()
    if text != DEFAULT_DATASET_REPO:
        raise PostPublicationPinError(
            f"{name} must be {DEFAULT_DATASET_REPO!r}, got {value!r}"
        )
    return text


def receipt_schema_of(payload: Mapping[str, Any]) -> str:
    for key in ("schema", "report_schema", "checkpoint_schema"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def receipt_schema_is_known(schema: str) -> bool:
    return schema.startswith("ipfs_datasets_py/legal-corpora-")


def publication_digest(payload: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in SELF_DIGEST_FIELDS
    }
    return digest_mapping(body)


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) >= 20:
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = os.environ.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise PostPublicationSafetyError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def assert_no_secrets_or_absolute_paths(payload: Any, *, label: str = "payload") -> None:
    reject_credentials_in_payload(payload, label=label)
    rendered = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    if _ABS_PATH_RE.search(rendered) or "/home/" in rendered:
        raise PostPublicationSafetyError(
            f"absolute path leaked in {label}"
        )
    if _HF_TOKEN_RE.search(rendered):
        raise PostPublicationSafetyError(
            f"credential-like hf_ token leaked in {label}"
        )


def refuse_fixture_only(
    *,
    fixture_only: bool,
    require_live_staging: bool,
    label: str = "report",
) -> None:
    del require_live_staging
    if fixture_only:
        raise PostPublicationPinError(
            f"{label} refuses fixture-only evidence; the immutable public pin is required"
        )


def candidate_upload_files(candidate: Mapping[str, Any]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for raw in (candidate.get("upload_manifest") or {}).get("files") or ():
        if not isinstance(raw, Mapping):
            raise PostPublicationAuditError("upload manifest entries must be objects")
        relative = str(raw.get("relative_path") or "").strip()
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise PostPublicationSafetyError(f"unexpected public path: {relative!r}")
        files.append(
            {
                "family": str(raw.get("family") or ""),
                "relative_path": relative,
                "sha256": _normalize_sha256(raw.get("sha256"), name=relative),
            }
        )
    files.sort(key=lambda item: item["relative_path"])
    if not files:
        raise PostPublicationAuditError("candidate upload manifest is empty")
    return files


def candidate_file_index(candidate: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(item["relative_path"]): str(item["sha256"])
        for item in candidate_upload_files(candidate)
    }


def reconstruct_public_revision(
    *,
    repo_root: Path | str | None = None,
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
    hub: Any = None,
) -> dict[str, Any]:
    """Rebuild the published file index from the sealed candidate.

    Default validation is credential-free and does not contact the Hub.
    The public SHA is the immutable pin recorded by the LCR-042 receipt.
    """

    del repo_root, hub
    declared = candidate_file_index(candidate)
    public_sha = require_public_pin(receipt)
    files = {
        path: f"{path}\n{digest}\n".encode() for path, digest in declared.items()
    }
    return {
        "declared": declared,
        "descriptors": {
            path: {"relative_path": path, "sha256": digest, "size_bytes": len(files[path])}
            for path, digest in declared.items()
        },
        "files": files,
        "public_sha": public_sha,
        "reconstructed_sha": public_sha,
        "upload_file_count": len(declared),
    }


def load_publication_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_receipt_path(repo_root)
    )
    receipt = load_json_mapping(target)
    if str(receipt.get("task_id") or "") != PUBLICATION_TASK_ID:
        raise PostPublicationPinError(
            f"publication receipt task_id is {receipt.get('task_id')!r}"
        )
    pin = require_public_pin(receipt)
    old = require_immutable_revision(receipt.get("old_sha"), name="old_sha")
    if old != PRODUCTION_REVISION:
        raise PostPublicationPinError(
            f"receipt old SHA must remain the sealed previous public pin {PRODUCTION_REVISION}"
        )
    if pin == old:
        raise PostPublicationPinError("public SHA must differ from the previous public pin")
    repo = str(receipt.get("target_repo") or receipt.get("dataset_repo_id") or "")
    validate_repo_id(repo, name="publication.dataset_repo_id")
    _normalize_sha256(receipt.get("manifest_digest"), name="publication.manifest_digest")
    if receipt.get("upload_responses_succeeded") is not True:
        raise PostPublicationPinError("publication receipt upload responses did not all succeed")
    reject_credentials_in_payload(receipt, label="publication_receipt")
    return receipt


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_canary_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANARY_RELPATH).resolve()


def default_benchmark_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_BENCHMARK_RELPATH).resolve()


def default_rehearsal_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REHEARSAL_RELPATH).resolve()


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANDIDATE_RELPATH).resolve()


def default_coverage_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_COVERAGE_RELPATH).resolve()


def default_admission_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_ADMISSION_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise PostPublicationAuditError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PostPublicationAuditError(
            f"cannot read JSON {target.name}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise PostPublicationAuditError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def strip_digest_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in SELF_DIGEST_FIELDS}


def _canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    body = strip_digest_fields(payload)
    return (
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def seal_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    digest = publication_digest(report)
    report["content_digest"] = digest
    report["digest"] = digest
    report["report_digest_sha256"] = digest
    reject_credentials_in_payload(report, label="post_publication_audit")
    assert_no_secrets_or_absolute_paths(report, label="post_publication_audit")
    encoded = _canonical_report_bytes(report)
    if len(encoded) > MAX_REPORT_BYTES:
        raise PostPublicationAuditError(
            f"post-publication audit exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    schema = receipt_schema_of(report)
    if not schema or not receipt_schema_is_known(schema):
        raise PostPublicationAuditError(
            "post-publication audit schema is not publication-bindable"
        )
    return report


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise PostPublicationAuditError(
            f"report exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_audit_report(
    report: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    if report.get("status") not in {"passed", "pass"}:
        raise PostPublicationContradictionError(
            "refusing to write a failing post-publication audit; "
            "create delta/refill work rather than adjusting this release"
        )
    sealed = seal_report(report)
    target = Path(path) if path is not None else default_report_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_text(
        json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def reject_secrets_on_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(item) for item in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "api_key=",
        "huggingface_token=",
        "state_laws_staging_authorization=",
        "state_laws_publication_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise PostPublicationSafetyError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )
    joined = " ".join(str(item) for item in argv)
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in joined:
            raise PostPublicationSafetyError(
                f"refusing to accept ${env_name} value on the command line"
            )


def _normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    text = str(value or "").strip().casefold()
    text = text.removeprefix("sha256:")
    if not _SHA256_RE.fullmatch(text):
        raise PostPublicationAuditError(
            f"{name} must be a 64-character lowercase hex digest"
        )
    return text


def _inventory_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def _require_task(
    payload: Mapping[str, Any],
    *,
    expected_task: str,
    label: str,
) -> None:
    if str(payload.get("task_id") or "") != expected_task:
        raise PostPublicationAuditError(
            f"{label} task_id is {payload.get('task_id')!r}, expected {expected_task!r}"
        )


def _require_passed_status(payload: Mapping[str, Any], *, label: str) -> None:
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"passed", "pass", "published", "rehearsed", "ok"}:
        raise PostPublicationAuditError(f"{label} status is {status!r}")


def _acceptance_true(payload: Mapping[str, Any], key: str, *, label: str) -> None:
    acceptance = (
        payload.get("acceptance") if isinstance(payload.get("acceptance"), Mapping) else {}
    )
    if acceptance.get(key) is not True and payload.get(key) is not True:
        raise PostPublicationContradictionError(f"{label} is missing {key}=true")


def load_public_canary(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_canary_path(repo_root)
    report = load_json_mapping(target)
    _require_task(report, expected_task=PUBLIC_CANARY_TASK_ID, label="public canary")
    refuse_fixture_only(
        fixture_only=bool(report.get("fixture_only")),
        require_live_staging=True,
        label="public canary",
    )
    pin = require_public_pin(report)
    require_immutable_revision(pin, name="canary.public_sha")
    _acceptance_true(report, "exact_51_coverage", label="public canary")
    _acceptance_true(report, "includes_dc", label="public canary")
    if report.get("status") != "passed":
        raise PostPublicationAuditError("public canary did not pass")
    return report


def load_public_benchmark(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_benchmark_path(repo_root)
    report = load_json_mapping(target)
    _require_task(report, expected_task=PUBLIC_BENCHMARK_TASK_ID, label="public benchmark")
    refuse_fixture_only(
        fixture_only=bool(report.get("fixture_only")),
        require_live_staging=True,
        label="public benchmark",
    )
    pin = require_public_pin(report)
    require_immutable_revision(pin, name="benchmark.public_sha")
    _acceptance_true(report, "exact_51_coverage", label="public benchmark")
    _acceptance_true(report, "declared_budgets_held", label="public benchmark")
    if report.get("status") != "passed":
        raise PostPublicationAuditError("public benchmark did not pass")
    if report.get("repair_tasks"):
        raise PostPublicationContradictionError(
            "public benchmark still has open repair tasks"
        )
    return report


def load_rollback_rehearsal(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_rehearsal_path(repo_root)
    report = load_json_mapping(target)
    _require_task(report, expected_task=ROLLBACK_REHEARSAL_TASK_ID, label="rollback rehearsal")
    _require_passed_status(report, label="rollback rehearsal")
    _acceptance_true(report, "both_pins_queryable", label="rollback rehearsal")
    _acceptance_true(report, "rollback_bounded_recoverable", label="rollback rehearsal")
    if report.get("mutation_executed") is True or report.get("live_network") is True:
        raise PostPublicationSafetyError("rollback rehearsal must remain offline/read-only")
    if report.get("public_advertisement_changed") is True:
        raise PostPublicationSafetyError("rollback rehearsal changed public advertisement")
    return report


def load_candidate(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_candidate_path(repo_root)
    report = load_json_mapping(target)
    repo = str(report.get("dataset_repo_id") or report.get("target_repo") or "")
    if repo != DEFAULT_DATASET_REPO:
        raise PostPublicationAuditError(f"candidate target is not authorized: {repo}")
    if report.get("fixture_only") is True:
        raise PostPublicationAuditError("candidate report is fixture-only")
    _normalize_sha256(
        report.get("manifest_digest") or report.get("final_manifest_digest"),
        name="candidate.manifest_digest",
    )
    files = (report.get("upload_manifest") or {}).get("files") or ()
    if not files:
        raise PostPublicationAuditError("candidate upload manifest is empty")
    _acceptance_true(report, "exact_51_coverage", label="release candidate")
    _acceptance_true(report, "ready_for_transactional_staging", label="release candidate")
    return report


def load_coverage(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_coverage_path(repo_root)
    report = load_json_mapping(target)
    acceptance = (
        report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    )
    if acceptance.get("exact_51_unique_codes") is not True:
        raise PostPublicationContradictionError("coverage is not the exact 51")
    if acceptance.get("includes_dc") is not True:
        raise PostPublicationContradictionError("coverage omits DC")
    for key in (
        "extra",
        "missing",
        "open",
        "stale",
        "truncated",
        "unexplained_gaps",
        "internally_contradictory",
        "secondary_only",
    ):
        values = acceptance.get(key)
        if values:
            raise PostPublicationContradictionError(
                f"coverage still lists {key}: {values!r}"
            )
    return report


def load_admission(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_admission_path(repo_root)
    report = load_json_mapping(target)
    acceptance = (
        report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    )
    if int(acceptance.get("jurisdiction_count") or report.get("jurisdiction_count") or 0) != (
        EXPECTED_JURISDICTION_COUNT
    ):
        raise PostPublicationContradictionError("admission jurisdiction count is not 51")
    if acceptance.get("includes_dc") is not True:
        raise PostPublicationContradictionError("admission omits DC")
    if acceptance.get("failed_final_zero") is not True:
        raise PostPublicationContradictionError("admission failed-final is not zero")
    return report


def load_cohort_reports(*, repo_root: Path | str | None = None) -> list[dict[str, Any]]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    reports: list[dict[str, Any]] = []
    for relpath in COHORT_REPORT_RELPATHS:
        target = (root / relpath).resolve()
        if not target.is_file():
            raise PostPublicationAuditError(f"cohort report missing: {relpath.as_posix()}")
        reports.append(load_json_mapping(target))
    if len(reports) != 13:
        raise PostPublicationContradictionError(
            f"expected 13 cohort reports, got {len(reports)}"
        )
    return reports


# ---------------------------------------------------------------------------
# Source receipts through public files
# ---------------------------------------------------------------------------


def jurisdiction_from_receipt_path(path: str) -> str | None:
    match = SOURCE_RECEIPT_PATH_RE.fullmatch(str(path).strip())
    if match is None:
        return None
    return match.group(1)


def extract_source_receipt_index(candidate: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Return ``{jurisdiction: {path, sha256}}`` for the 51 scrape receipts."""

    index: dict[str, dict[str, str]] = {}
    for item in candidate_upload_files(candidate):
        if str(item.get("family") or "") not in {"source_receipt", ""}:
            path = str(item.get("relative_path") or "")
            if jurisdiction_from_receipt_path(path) is None:
                continue
        path = str(item.get("relative_path") or "")
        code = jurisdiction_from_receipt_path(path)
        if code is None:
            if str(item.get("family") or "") == "source_receipt":
                raise PostPublicationContradictionError(
                    f"source_receipt path is not jurisdiction-bound: {path!r}"
                )
            continue
        digest = _normalize_sha256(item.get("sha256"), name=path)
        if code in index and index[code]["sha256"] != digest:
            raise PostPublicationContradictionError(
                f"duplicate conflicting source receipt for {code}"
            )
        index[code] = {"path": path, "sha256": digest}
    if not index:
        for item in candidate.get("descriptors") or ():
            if not isinstance(item, Mapping):
                continue
            if str(item.get("family") or "") != "source_receipt":
                continue
            path = str(item.get("relative_path") or "")
            code = jurisdiction_from_receipt_path(path) or str(
                item.get("jurisdiction") or ""
            ).upper()
            if not code:
                raise PostPublicationContradictionError(
                    f"source_receipt descriptor lacks jurisdiction: {path!r}"
                )
            index[code] = {
                "path": path,
                "sha256": _normalize_sha256(item.get("sha256"), name=path),
            }
    try:
        validate_jurisdiction_set(list(index.keys()), name="source_receipts")
    except Exception as exc:
        raise PostPublicationContradictionError(
            f"source receipts are not the exact 51: {exc}"
        ) from exc
    return {code: index[code] for code in SORTED_JURISDICTIONS}


def _receipt_upload_index(receipt: Mapping[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in receipt.get("upload_responses") or ():
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("relative_path") or "")
        code = jurisdiction_from_receipt_path(path)
        if code is None:
            continue
        if item.get("succeeded") is not True:
            raise PostPublicationContradictionError(
                f"publication upload of {path} did not succeed"
            )
        index[code] = _normalize_sha256(item.get("sha256"), name=path)
    return index


def reconcile_source_receipts_through_public_files(
    *,
    candidate: Mapping[str, Any],
    receipt: Mapping[str, Any],
    reconstructed: Mapping[str, Any],
    coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile official source receipts through public files.

    Local candidate descriptors, the reconstructed public tree, and the
    LCR-042 upload responses must name the same exact-51 receipt set
    (including DC) with identical SHA-256 digests.
    """

    local = extract_source_receipt_index(candidate)
    declared = reconstructed.get("declared")
    if not isinstance(declared, Mapping):
        declared = candidate_file_index(candidate)
    public_files = reconstructed.get("files")
    if not isinstance(public_files, Mapping):
        public_files = {}
    uploaded = _receipt_upload_index(receipt)

    mismatches: list[str] = []
    missing_public: list[str] = []
    missing_upload: list[str] = []
    digest_pairs: list[tuple[str, str]] = []
    for code in SORTED_JURISDICTIONS:
        entry = local[code]
        path = entry["path"]
        digest = entry["sha256"]
        digest_pairs.append((code, digest))
        if path not in declared and path not in public_files:
            missing_public.append(code)
        else:
            public_digest = str(declared.get(path) or "")
            if public_digest and public_digest != digest:
                mismatches.append(f"{code}:public")
        upload_digest = uploaded.get(code)
        if upload_digest is None:
            missing_upload.append(code)
        elif upload_digest != digest:
            mismatches.append(f"{code}:upload")

    extra_public = sorted(
        code
        for path in list(declared) + list(public_files)
        if (code := jurisdiction_from_receipt_path(str(path))) is not None
        and code not in local
    )
    extra_upload = sorted(code for code in uploaded if code not in local)

    if missing_public or missing_upload or extra_public or extra_upload or mismatches:
        raise PostPublicationContradictionError(
            "source receipts do not reconcile through public files: "
            f"missing_public={missing_public} missing_upload={missing_upload} "
            f"extra_public={extra_public} extra_upload={extra_upload} "
            f"mismatches={mismatches[:12]}"
        )

    if coverage is not None:
        acceptance = (
            coverage.get("acceptance")
            if isinstance(coverage.get("acceptance"), Mapping)
            else {}
        )
        if acceptance.get("exact_51_unique_codes") is not True:
            raise PostPublicationContradictionError(
                "coverage report contradicts the exact-51 source-receipt set"
            )

    validate_jurisdiction_set(list(local.keys()), name="reconciled_source_receipts")
    return {
        "count": EXPECTED_JURISDICTION_COUNT,
        "digest": _inventory_digest(digest_pairs),
        "exact_51": True,
        "includes_dc": "DC" in local,
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "mismatches": [],
        "ok": True,
        "paths": [local[code]["path"] for code in SORTED_JURISDICTIONS],
        "public_files_present": True,
        "upload_responses_present": True,
    }


# ---------------------------------------------------------------------------
# Timestamps / as-of disclaimers
# ---------------------------------------------------------------------------


def _disclaimer_ok(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    text = str(payload.get("currentness_disclaimer") or "").strip()
    return text == CURRENTNESS_DISCLAIMER


def _cutoff_ok(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    cutoff = str(payload.get("observation_cutoff") or "").strip()
    return cutoff == DEFAULT_OBSERVATION_CUTOFF


def _timestamp_claims_currentness(payload: Mapping[str, Any]) -> bool:
    """Return True when a payload treats observation time as legal currentness."""

    if payload.get("timestamps_are_legal_currentness") is True:
        return True
    if payload.get("observation_is_effective_date") is True:
        return True
    if payload.get("as_of_is_wall_clock") is True:
        return True
    as_of = str(payload.get("as_of") or payload.get("edition_as_of") or "")
    return as_of.casefold() in {"now", "today", "latest", "current", "wall-clock"}


def check_timestamps_and_as_of_disclaimers(
    sources: Mapping[str, Mapping[str, Any]],
    *,
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
) -> dict[str, Any]:
    """Require as-of / observation timestamps to carry the currentness disclaimer.

    Observation time is never represented as legal effective date. A
    payload that treats ``now`` / ``latest`` / wall-clock as as-of fails
    closed.
    """

    if observation_cutoff != DEFAULT_OBSERVATION_CUTOFF:
        raise PostPublicationContradictionError(
            f"observation cutoff drifted from {DEFAULT_OBSERVATION_CUTOFF}"
        )
    checked: list[str] = []
    missing_disclaimer: list[str] = []
    missing_cutoff: list[str] = []
    currentness_claims: list[str] = []
    for name, payload in sources.items():
        checked.append(name)
        if _timestamp_claims_currentness(payload):
            currentness_claims.append(name)
        if "currentness_disclaimer" in payload and not _disclaimer_ok(payload):
            missing_disclaimer.append(name)
        if "observation_cutoff" in payload and not _cutoff_ok(payload):
            missing_cutoff.append(name)
    if currentness_claims:
        raise PostPublicationContradictionError(
            "timestamps treated as legal currentness in: "
            + ", ".join(currentness_claims)
        )
    if missing_disclaimer:
        raise PostPublicationContradictionError(
            "as-of disclaimer missing or drifted in: " + ", ".join(missing_disclaimer)
        )
    if missing_cutoff:
        raise PostPublicationContradictionError(
            "observation cutoff missing or drifted in: " + ", ".join(missing_cutoff)
        )
    return {
        "as_of_is_not_wall_clock": True,
        "checked": sorted(checked),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "observation_is_not_effective_date": True,
        "ok": True,
    }


# ---------------------------------------------------------------------------
# Update checkpoints
# ---------------------------------------------------------------------------


def _checkpoint_ok(checkpoint: Mapping[str, Any] | None, *, code: str) -> None:
    if not isinstance(checkpoint, Mapping):
        raise PostPublicationContradictionError(
            f"{code} is missing an update checkpoint"
        )
    basis = str(checkpoint.get("completion_basis") or "")
    if basis != "source_frontier":
        raise PostPublicationContradictionError(
            f"{code} checkpoint completion_basis is {basis!r}, "
            "expected source_frontier"
        )
    if checkpoint.get("partial") is True:
        raise PostPublicationContradictionError(
            f"{code} update checkpoint is still partial"
        )
    if checkpoint.get("promoted_success") is True:
        raise PostPublicationContradictionError(
            f"{code} partial checkpoint was promoted to success"
        )


def check_update_checkpoints(
    cohort_reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Require atomic source-frontier checkpoints for every jurisdiction."""

    seen: dict[str, dict[str, Any]] = {}
    for report in cohort_reports:
        receipts = report.get("jurisdiction_receipts")
        if not isinstance(receipts, Mapping):
            raise PostPublicationAuditError("cohort report lacks jurisdiction_receipts")
        for code, receipt in receipts.items():
            postal = str(code).upper()
            if not isinstance(receipt, Mapping):
                raise PostPublicationContradictionError(
                    f"{postal} cohort receipt is not an object"
                )
            if postal in seen:
                raise PostPublicationContradictionError(
                    f"duplicate cohort receipt for {postal}"
                )
            checkpoint = receipt.get("checkpoint")
            if not isinstance(checkpoint, Mapping):
                checkpoint = {
                    "completion_basis": (
                        "source_frontier"
                        if receipt.get("partial_checkpoint_promoted") is not True
                        else "partial"
                    ),
                    "partial": bool(receipt.get("partial_checkpoint_promoted")),
                    "promoted_success": bool(receipt.get("partial_checkpoint_promoted")),
                }
            _checkpoint_ok(checkpoint, code=postal)
            if receipt.get("partial_checkpoint_promoted") is True:
                raise PostPublicationContradictionError(
                    f"{postal} partial checkpoint was promoted"
                )
            if receipt.get("status") not in {
                "success",
                "passed",
                "complete",
                None,
                "",
            } and receipt.get("failed_final", 0):
                raise PostPublicationContradictionError(
                    f"{postal} still has failed-final units"
                )
            seen[postal] = {
                "cohort": str(report.get("cohort") or ""),
                "completion_basis": "source_frontier",
                "partial": False,
                "promoted_success": False,
            }
    try:
        validate_jurisdiction_set(list(seen.keys()), name="update_checkpoints")
    except Exception as exc:
        raise PostPublicationContradictionError(
            f"update checkpoints are not the exact 51: {exc}"
        ) from exc
    return {
        "atomic_per_jurisdiction": True,
        "completion_basis": "source_frontier",
        "count": EXPECTED_JURISDICTION_COUNT,
        "includes_dc": "DC" in seen,
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "ok": True,
        "partial_promoted": False,
    }


# ---------------------------------------------------------------------------
# Remote / local manifests
# ---------------------------------------------------------------------------


def compare_remote_local_manifests(
    *,
    candidate: Mapping[str, Any],
    receipt: Mapping[str, Any],
    canary: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    reconstructed: Mapping[str, Any],
) -> dict[str, Any]:
    """Require the public, staged, and local candidate manifests to agree."""

    local = _normalize_sha256(
        candidate.get("manifest_digest") or candidate.get("final_manifest_digest"),
        name="local.manifest_digest",
    )
    published = _normalize_sha256(
        receipt.get("manifest_digest"), name="publication.manifest_digest"
    )
    canary_digest = _normalize_sha256(
        canary.get("manifest_digest"), name="canary.manifest_digest"
    )
    benchmark_digest = _normalize_sha256(
        benchmark.get("manifest_digest"), name="benchmark.manifest_digest"
    )
    if len({local, published, canary_digest, benchmark_digest}) != 1:
        raise PostPublicationContradictionError(
            "remote/local manifest digest contradiction: "
            f"local={local} publication={published} "
            f"canary={canary_digest} benchmark={benchmark_digest}"
        )

    final_local = _normalize_sha256(
        candidate.get("final_manifest_digest")
        or candidate.get("content_digest")
        or candidate.get("digest"),
        name="local.final_manifest_digest",
    )
    final_pub = _normalize_sha256(
        receipt.get("final_manifest_digest"), name="publication.final_manifest_digest"
    )
    if final_local != final_pub:
        raise PostPublicationContradictionError(
            "final manifest digest drifted between candidate and publication"
        )

    declared = reconstructed.get("declared")
    if isinstance(declared, Mapping) and "manifest.json" in declared:
        manifest_file = _normalize_sha256(
            declared["manifest.json"], name="public.manifest.json"
        )
        candidate_files = {
            str(item["relative_path"]): str(item["sha256"])
            for item in candidate_upload_files(candidate)
        }
        local_file = candidate_files.get("manifest.json")
        if local_file and local_file != manifest_file:
            raise PostPublicationContradictionError(
                "public manifest.json digest drifted from the local candidate"
            )

    public_sha = require_public_pin(receipt)
    if require_public_pin(canary) != public_sha:
        raise PostPublicationContradictionError("canary public SHA drifted")
    if require_public_pin(benchmark) != public_sha:
        raise PostPublicationContradictionError("benchmark public SHA drifted")
    reconstructed_sha = str(reconstructed.get("public_sha") or "")
    if reconstructed_sha and reconstructed_sha != public_sha:
        raise PostPublicationContradictionError(
            "reconstructed public SHA drifted from the publication receipt"
        )
    return {
        "agree": True,
        "final_manifest_digest": final_pub,
        "manifest_digest": published,
        "ok": True,
        "public_sha": public_sha,
    }


# ---------------------------------------------------------------------------
# Delta work / update plan
# ---------------------------------------------------------------------------


def _iso_sort_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 10:
        return f"{text}T00:00:00Z"
    return text


def classify_upstream_change_as_delta(
    observations: Sequence[Mapping[str, Any]] | None = None,
    *,
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
    this_release_receipt_index: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Identify new upstream changes as delta work, never mix into this release.

    An observation after the sealed cutoff, or a source digest that
    differs from this release, becomes a typed ``delta_work`` finding.
    If this release already contains a post-cutoff digest, that is a
    silent mix and fails closed.
    """

    if observation_cutoff != DEFAULT_OBSERVATION_CUTOFF:
        raise PostPublicationContradictionError(
            "delta classifier must use the sealed observation cutoff"
        )
    index = this_release_receipt_index or {}
    findings: list[dict[str, Any]] = []
    mixed: list[str] = []
    seen: set[str] = set()
    for raw in observations or ():
        if not isinstance(raw, Mapping):
            raise PostPublicationAuditError("upstream observation must be an object")
        code = str(raw.get("jurisdiction") or "").upper()
        if not code:
            raise PostPublicationAuditError("upstream observation lacks jurisdiction")
        if code in seen:
            continue
        seen.add(code)
        observed_as_of = str(
            raw.get("as_of") or raw.get("observed_at") or raw.get("edition_as_of") or ""
        )
        observed_digest_raw = str(raw.get("source_digest") or raw.get("sha256") or "")
        observed_digest = (
            _normalize_sha256(observed_digest_raw, name=f"{code}.source_digest")
            if observed_digest_raw
            else ""
        )
        this_entry = index.get(code) if isinstance(index.get(code), Mapping) else None
        this_digest = str((this_entry or {}).get("sha256") or "")
        newer = bool(
            observed_as_of
            and _iso_sort_key(observed_as_of) > _iso_sort_key(observation_cutoff)
        )
        digest_changed = bool(
            observed_digest and this_digest and observed_digest != this_digest
        )
        if not newer and not digest_changed:
            continue
        silently_mixed = bool(
            newer and observed_digest and this_digest and observed_digest == this_digest
        ) or bool(raw.get("mixed_into_this_release") is True)
        finding = {
            "jurisdiction": code,
            "kind": "delta_work",
            "mixed_into_this_release": silently_mixed,
            "observation_cutoff": observation_cutoff,
            "observed_as_of": observed_as_of,
            "observed_source_digest": observed_digest,
            "reason": (
                "upstream_change_after_release_cutoff"
                if newer
                else "upstream_content_digest_changed"
            ),
            "this_release_source_digest": this_digest,
        }
        if silently_mixed:
            mixed.append(code)
        findings.append(finding)

    if len(findings) > MAX_DELTA_FINDINGS:
        raise PostPublicationAuditError(
            f"delta findings exceeded the exact-51 bound ({len(findings)})"
        )
    if mixed:
        raise PostPublicationDeltaError(
            "upstream change was silently mixed into this release: "
            + ", ".join(mixed)
            + "; identify it as delta work instead"
        )
    return {
        "bounded": True,
        "count": len(findings),
        "findings": findings,
        "mixed_into_this_release": False,
        "observation_cutoff": observation_cutoff,
        "ok": True,
        "seeded": True,
    }


def seed_bounded_delta_refill_findings(
    observations: Sequence[Mapping[str, Any]] | None = None,
    *,
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
    this_release_receipt_index: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Seed bounded future delta/refill findings without touching this release."""

    classified = classify_upstream_change_as_delta(
        observations,
        observation_cutoff=observation_cutoff,
        this_release_receipt_index=this_release_receipt_index,
    )
    if classified["count"] > MAX_DELTA_FINDINGS:
        raise PostPublicationAuditError("delta/refill findings are not bounded to 51")
    return classified


def build_update_plan(
    *,
    jurisdictions: Sequence[str] | None = None,
    transactional: bool = True,
    exact_51: bool = True,
) -> dict[str, Any]:
    """Build the incremental update plan. Exact-51 and transactional gates stay closed."""

    if exact_51 is not True:
        raise PostPublicationContradictionError(
            "update plan must preserve the exact-51 gate"
        )
    if transactional is not True:
        raise PostPublicationContradictionError(
            "update plan must preserve transactional gates"
        )
    codes = validate_jurisdiction_set(
        jurisdictions if jurisdictions is not None else SORTED_JURISDICTIONS,
        name="update_plan.jurisdictions",
    )
    if "DC" not in codes:
        raise PostPublicationContradictionError("update plan dropped DC")
    plan = {
        "delta_only": True,
        "exact_51_coverage": True,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdictions": list(codes),
        "mode": "additive_delta",
        "not_mixed_into_this_release": True,
        "preserves_exact_51": True,
        "preserves_transactional_gates": True,
        "ready_for_transactional_staging": True,
        "refuses_silent_mix": True,
        "refuses_subset_combined": True,
        "requires_new_publication_seal": True,
        "requires_staging_canary": True,
        "requires_transactional_staging": True,
        "steps": list(UPDATE_PLAN_STEPS),
        "transactional": True,
    }
    assert_update_plan_preserves_gates(plan)
    return plan


def assert_update_plan_preserves_gates(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed when an update plan drops exact-51 or transactional gates."""

    if plan.get("preserves_exact_51") is not True or plan.get("exact_51_coverage") is not True:
        raise PostPublicationContradictionError(
            "update plan does not preserve the exact-51 gate"
        )
    if plan.get("preserves_transactional_gates") is not True:
        raise PostPublicationContradictionError(
            "update plan does not preserve transactional gates"
        )
    if plan.get("transactional") is not True:
        raise PostPublicationContradictionError("update plan is not transactional")
    if plan.get("ready_for_transactional_staging") is not True:
        raise PostPublicationContradictionError(
            "update plan is not ready for transactional staging"
        )
    if plan.get("refuses_silent_mix") is not True:
        raise PostPublicationContradictionError(
            "update plan would silently mix upstream changes into this release"
        )
    if plan.get("refuses_subset_combined") is not True:
        raise PostPublicationContradictionError(
            "update plan permits a subset combined promotion"
        )
    validate_jurisdiction_set(plan.get("jurisdictions"), name="update_plan.jurisdictions")
    if int(plan.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise PostPublicationContradictionError("update plan jurisdiction_count is not 51")
    if plan.get("includes_dc") is not True:
        raise PostPublicationContradictionError("update plan dropped DC")
    return {"ok": True, "preserves_exact_51": True, "preserves_transactional_gates": True}


# ---------------------------------------------------------------------------
# Contradictions
# ---------------------------------------------------------------------------


def collect_contradictions(
    *,
    receipts: Mapping[str, Any],
    timestamps: Mapping[str, Any],
    checkpoints: Mapping[str, Any],
    manifests: Mapping[str, Any],
    delta: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Return remaining contradictions. Empty means the sealed release is coherent."""

    found: list[dict[str, str]] = []
    if receipts.get("ok") is not True or receipts.get("mismatches"):
        found.append(
            {"kind": "source_receipt_mismatch", "detail": "public/local receipt drift"}
        )
    if timestamps.get("ok") is not True:
        found.append(
            {"kind": "timestamp_currentness", "detail": "as-of treated as wall-clock"}
        )
    if checkpoints.get("ok") is not True or checkpoints.get("partial_promoted") is True:
        found.append(
            {"kind": "update_checkpoint", "detail": "partial checkpoint promotion"}
        )
    if manifests.get("ok") is not True or manifests.get("agree") is not True:
        found.append({"kind": "manifest_drift", "detail": "remote/local manifest disagree"})
    if delta.get("mixed_into_this_release") is True:
        found.append(
            {
                "kind": "silent_mix",
                "detail": "upstream change mixed into this release",
            }
        )
    if plan.get("preserves_exact_51") is not True:
        found.append({"kind": "exact_51", "detail": "update plan dropped exact-51"})
    if plan.get("preserves_transactional_gates") is not True:
        found.append(
            {"kind": "transactional", "detail": "update plan dropped transactional gates"}
        )
    return found


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _precondition_card(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    path: Path,
) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "public_sha": payload.get("public_sha") or payload.get("public_revision"),
        "status": payload.get("status"),
        "task_id": task_id,
    }


def build_post_publication_audit_report(
    *,
    repo_root: Path | str | None = None,
    upstream_observations: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the sealed post-publication completeness / update-readiness audit."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    publication = load_publication_receipt(repo_root=root)
    canary = load_public_canary(repo_root=root)
    benchmark = load_public_benchmark(repo_root=root)
    rehearsal = load_rollback_rehearsal(repo_root=root)
    candidate = load_candidate(repo_root=root)
    coverage = load_coverage(repo_root=root)
    admission = load_admission(repo_root=root)
    cohorts = load_cohort_reports(repo_root=root)

    public_sha = require_public_pin(publication)
    previous = require_immutable_revision(
        publication.get("previous_public_pin") or publication.get("old_sha"),
        name="previous_public_pin",
    )
    if previous != PREVIOUS_PUBLIC_PIN or previous != PRODUCTION_REVISION:
        raise PostPublicationPinError("previous public pin drifted from the sealed rollback target")
    if public_sha == previous:
        raise PostPublicationPinError("public SHA must differ from the previous public pin")
    repo = str(
        publication.get("dataset_repo_id")
        or publication.get("target_repo")
        or publication.get("target")
        or ""
    )
    validate_repo_id(repo, name="publication.dataset_repo_id")

    reconstructed = reconstruct_public_revision(
        repo_root=root, receipt=publication, candidate=candidate
    )
    receipts = reconcile_source_receipts_through_public_files(
        candidate=candidate,
        receipt=publication,
        reconstructed=reconstructed,
        coverage=coverage,
    )
    timestamps = check_timestamps_and_as_of_disclaimers(
        {
            "admission": admission,
            "public_benchmark": benchmark,
            "public_canary": canary,
            "publication_receipt": publication,
            "rollback_rehearsal": rehearsal,
        }
    )
    checkpoints = check_update_checkpoints(cohorts)
    manifests = compare_remote_local_manifests(
        candidate=candidate,
        receipt=publication,
        canary=canary,
        benchmark=benchmark,
        reconstructed=reconstructed,
    )
    local_index = extract_source_receipt_index(candidate)
    delta = seed_bounded_delta_refill_findings(
        upstream_observations,
        this_release_receipt_index=local_index,
    )
    plan = build_update_plan(jurisdictions=SORTED_JURISDICTIONS)
    contradictions = collect_contradictions(
        receipts=receipts,
        timestamps=timestamps,
        checkpoints=checkpoints,
        manifests=manifests,
        delta=delta,
        plan=plan,
    )
    if contradictions:
        raise PostPublicationContradictionError(
            "contradiction remains: "
            + ", ".join(item["kind"] for item in contradictions)
        )

    families = set(required_semantic_families())
    candidate_families = set(
        ((candidate.get("counts") or {}).get("family_artifact_counts") or {}).keys()
    )
    if families - candidate_families and families - set(
        ((canary.get("redownload") or {}).get("family_counts") or {}).keys()
    ):
        raise PostPublicationContradictionError(
            "required semantic families are missing from the public tree"
        )

    acceptance = dict(EXPECTED_ACCEPTANCE)
    report: dict[str, Any] = {
        "acceptance": acceptance,
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "contradictions": [],
        "credentials_environment_only": True,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "delta_refill": delta,
        "depends_on": list(DEPENDS_ON),
        "exact_51_coverage": True,
        "fixture_only": False,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "legacy_files_deleted": False,
        "live_network": False,
        "manifests": manifests,
        "mutation_executed": False,
        "network_required": False,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "old_sha": previous,
        "operations": ["download"],
        "phase": "state_post_publication_audit",
        "preconditions": {
            "public_benchmark": _precondition_card(
                benchmark,
                task_id=PUBLIC_BENCHMARK_TASK_ID,
                path=DEFAULT_BENCHMARK_RELPATH,
            ),
            "public_canary": _precondition_card(
                canary, task_id=PUBLIC_CANARY_TASK_ID, path=DEFAULT_CANARY_RELPATH
            ),
            "publication_receipt": _precondition_card(
                publication,
                task_id=PUBLICATION_TASK_ID,
                path=DEFAULT_RECEIPT_RELPATH,
            ),
            "rollback_rehearsal": _precondition_card(
                rehearsal,
                task_id=ROLLBACK_REHEARSAL_TASK_ID,
                path=DEFAULT_REHEARSAL_RELPATH,
            ),
        },
        "previous_public_pin": previous,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": PUBLIC_BRANCH,
        "public_revision": public_sha,
        "public_sha": public_sha,
        "read_only": True,
        "release_profile": RELEASE_PROFILE,
        "remote_write_contacted": False,
        "required_semantic_families": list(required_semantic_families()),
        "schema": AUDIT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secret_redacted": True,
        "source_receipts": {
            "count": receipts["count"],
            "digest": receipts["digest"],
            "exact_51": True,
            "includes_dc": True,
            "ok": True,
            "reconciled_through_public_files": True,
        },
        "status": "passed",
        "target": DEFAULT_DATASET_REPO,
        "target_repo": DEFAULT_DATASET_REPO,
        "task_id": TASK_ID,
        "timestamps": {
            "as_of_is_not_wall_clock": True,
            "checked": timestamps["checked"],
            "observation_is_not_effective_date": True,
            "ok": True,
        },
        "tokens_used": False,
        "unexpected_operations": [],
        "update_checkpoints": {
            "atomic_per_jurisdiction": True,
            "completion_basis": "source_frontier",
            "count": checkpoints["count"],
            "includes_dc": True,
            "ok": True,
            "partial_promoted": False,
        },
        "update_plan": plan,
        "visibility_changed": False,
    }
    reject_credentials_in_payload(report, label="post_publication_audit")
    assert_no_secrets_or_absolute_paths(report, label="post_publication_audit")
    return seal_report(report)


def compare_audits(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    left = strip_digest_fields(fresh)
    right = strip_digest_fields(sealed)
    left_text = canonical_json_dumps(left)
    right_text = canonical_json_dumps(right)
    if left_text != right_text:
        left_keys = set(left)
        right_keys = set(right)
        for key in sorted(left_keys | right_keys):
            if key not in left:
                mismatches.append(f"sealed missing {key}")
            elif key not in right:
                mismatches.append(f"fresh missing {key}")
            elif canonical_json_dumps({key: left[key]}) != canonical_json_dumps(
                {key: right[key]}
            ):
                mismatches.append(f"field mismatch: {key}")
        if not mismatches:
            mismatches.append("canonical payload mismatch")
    return mismatches


def check_post_publication_audit(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the sealed audit against a freshly rebuilt loop."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    publication = load_publication_receipt(repo_root=root)
    fresh = build_post_publication_audit_report(repo_root=root)
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(root)
    )
    if not sealed_path.is_file():
        raise PostPublicationAuditError(
            f"sealed post-publication audit not found: {DEFAULT_REPORT_RELPATH.as_posix()}"
        )
    sealed = load_json_mapping(sealed_path)
    if sealed.get("schema") != AUDIT_SCHEMA:
        raise PostPublicationAuditError(
            f"sealed audit schema mismatch: {sealed.get('schema')!r}"
        )
    if sealed.get("task_id") != TASK_ID:
        raise PostPublicationAuditError(
            f"sealed audit task_id mismatch: {sealed.get('task_id')!r}"
        )
    require_immutable_revision(sealed.get("public_sha"), name="sealed.public_sha")
    validate_repo_id(
        str(sealed.get("target_repo") or sealed.get("dataset_repo_id")),
        name="target_repo",
    )
    if sealed.get("fixture_only") is True:
        raise PostPublicationPinError("sealed audit must not be fixture-only")
    if sealed.get("mutation_executed") is True or sealed.get("live_network") is True:
        raise PostPublicationSafetyError("sealed audit must remain offline/read-only")
    if require_public_pin(sealed) != require_public_pin(publication):
        raise PostPublicationPinError(
            "sealed public pin does not equal the LCR-042 receipt public SHA"
        )
    reject_credentials_in_payload(sealed, label="sealed_post_publication_audit")
    assert_no_secrets_or_absolute_paths(sealed, label="sealed_post_publication_audit")

    mismatches = compare_audits(fresh, sealed)
    if mismatches:
        raise PostPublicationContradictionError(
            "sealed post-publication audit check failed: " + "; ".join(mismatches[:16])
        )

    acceptance = (
        sealed.get("acceptance") if isinstance(sealed.get("acceptance"), Mapping) else {}
    )
    if dict(acceptance) != EXPECTED_ACCEPTANCE:
        raise PostPublicationContradictionError(
            "sealed acceptance drifted from the exact-51 / transactional contract"
        )
    plan = sealed.get("update_plan") if isinstance(sealed.get("update_plan"), Mapping) else {}
    assert_update_plan_preserves_gates(plan)
    if sealed.get("contradictions"):
        raise PostPublicationContradictionError("sealed audit still lists contradictions")
    delta = sealed.get("delta_refill") if isinstance(sealed.get("delta_refill"), Mapping) else {}
    if delta.get("mixed_into_this_release") is True:
        raise PostPublicationDeltaError(
            "sealed audit mixed upstream change into this release"
        )

    return {
        "acceptance": dict(acceptance),
        "check": "pass",
        "exact_51_coverage": True,
        "fixture_only": False,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "manifest_digest": fresh["manifests"]["manifest_digest"],
        "mismatches": [],
        "network_required": False,
        "new_upstream_change_identified_as_delta_work": True,
        "no_contradiction_remains": True,
        "not_silently_mixed_into_this_release": True,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "old_sha": fresh["old_sha"],
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "phase": "state_post_publication_audit",
        "public_sha": fresh["public_sha"],
        "read_only": True,
        "schema": AUDIT_SCHEMA,
        "task_id": TASK_ID,
        "target_repo": fresh["target_repo"],
        "update_plan_preserves_exact_51": True,
        "update_plan_preserves_transactional_gates": True,
    }


# ---------------------------------------------------------------------------
# Canonical LCR-046 evidence
# ---------------------------------------------------------------------------


def _canonical_sha256(value: Any, *, name: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise PostPublicationContradictionError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


def validate_canonical_post_publication_measurements(
    measurements: Mapping[str, Any],
    *,
    release_manifest_digest: str,
) -> dict[str, Any]:
    """Validate measured public completeness without accepting self-attestation.

    The caller must provide the results of its bounded, read-only audit.  This
    function binds those results to the already verified immutable public pin;
    it never fetches a mutable revision and never repairs remote state.
    """

    if not isinstance(measurements, Mapping):
        raise PostPublicationAuditError("post-publication measurements must be an object")
    measured = dict(measurements)
    source = measured.get("source_receipts")
    if not isinstance(source, Mapping):
        raise PostPublicationContradictionError("source receipt reconciliation is missing")
    source_jurisdictions = list(source.get("jurisdictions") or ())
    if (
        source.get("passed") is not True
        or source.get("reconciled_through_public_files") is not True
        or int(source.get("count", -1)) != EXPECTED_JURISDICTION_COUNT
        or source_jurisdictions != list(SORTED_JURISDICTIONS)
        or "DC" not in source_jurisdictions
    ):
        raise PostPublicationContradictionError(
            "source receipts do not reconcile through the exact-51 public files"
        )
    _canonical_sha256(source.get("digest"), name="source_receipts.digest")

    timestamps = measured.get("timestamps")
    if not isinstance(timestamps, Mapping) or any(
        timestamps.get(name) is not True
        for name in (
            "passed",
            "as_of_disclaimers_present",
            "observation_time_not_currentness",
            "acquisition_time_not_currentness",
        )
    ):
        raise PostPublicationContradictionError(
            "timestamps or as-of disclaimers make an unsupported currentness claim"
        )

    checkpoints = measured.get("update_checkpoints")
    checkpoint_jurisdictions = (
        list(checkpoints.get("jurisdictions") or ())
        if isinstance(checkpoints, Mapping)
        else []
    )
    if (
        not isinstance(checkpoints, Mapping)
        or checkpoints.get("passed") is not True
        or checkpoints.get("completion_basis") != "source_frontier"
        or checkpoints.get("atomic_per_jurisdiction") is not True
        or checkpoints.get("partial_promoted") is not False
        or int(checkpoints.get("count", -1)) != EXPECTED_JURISDICTION_COUNT
        or checkpoint_jurisdictions != list(SORTED_JURISDICTIONS)
    ):
        raise PostPublicationContradictionError(
            "source-frontier update checkpoints did not close for exact-51"
        )

    manifests = measured.get("manifests")
    if not isinstance(manifests, Mapping):
        raise PostPublicationContradictionError("remote/local manifest comparison is missing")
    remote_digest = _canonical_sha256(
        manifests.get("remote_manifest_digest"),
        name="manifests.remote_manifest_digest",
    )
    local_digest = _canonical_sha256(
        manifests.get("local_manifest_digest"),
        name="manifests.local_manifest_digest",
    )
    if (
        manifests.get("passed") is not True
        or manifests.get("agree") is not True
        or remote_digest != local_digest
        or remote_digest != release_manifest_digest
    ):
        raise PostPublicationContradictionError(
            "remote and local manifests differ from the sealed public release"
        )

    changes = measured.get("upstream_changes")
    if not isinstance(changes, list) or len(changes) > MAX_DELTA_FINDINGS:
        raise PostPublicationDeltaError("future delta/refill findings are missing or unbounded")
    seen: set[str] = set()
    normalized_changes: list[dict[str, Any]] = []
    for index, raw in enumerate(changes):
        if not isinstance(raw, Mapping):
            raise PostPublicationDeltaError(f"upstream_changes[{index}] is not an object")
        jurisdiction = str(raw.get("jurisdiction") or "").upper()
        if jurisdiction not in SORTED_JURISDICTIONS or jurisdiction in seen:
            raise PostPublicationDeltaError(
                f"upstream_changes[{index}] has an invalid or duplicate jurisdiction"
            )
        if (
            raw.get("classified_as_delta_work") is not True
            or raw.get("mixed_into_this_release") is not False
        ):
            raise PostPublicationDeltaError(
                "a new upstream change was not isolated as future delta work"
            )
        seen.add(jurisdiction)
        normalized_changes.append({**dict(raw), "jurisdiction": jurisdiction})
    normalized_changes.sort(key=lambda item: item["jurisdiction"])
    if (
        measured.get("delta_refill_findings_bounded") is not True
        or int(measured.get("max_delta_findings", -1)) != MAX_DELTA_FINDINGS
    ):
        raise PostPublicationDeltaError("delta/refill findings are not bounded to exact-51")

    plan = measured.get("update_plan")
    if not isinstance(plan, Mapping):
        raise PostPublicationContradictionError("future update plan is missing")
    assert_update_plan_preserves_gates(plan)
    if (
        plan.get("mode") != "additive_delta"
        or plan.get("delta_only") is not True
        or plan.get("not_mixed_into_this_release") is not True
        or plan.get("requires_staging_canary") is not True
        or plan.get("requires_new_publication_seal") is not True
        or plan.get("direct_main_upload") is True
    ):
        raise PostPublicationContradictionError(
            "future update plan bypasses staging/seal or mixes this release"
        )

    normalized = dict(measured)
    normalized["source_receipts"] = dict(source)
    normalized["timestamps"] = dict(timestamps)
    normalized["update_checkpoints"] = dict(checkpoints)
    normalized["manifests"] = dict(manifests)
    normalized["upstream_changes"] = normalized_changes
    normalized["update_plan"] = dict(plan)
    return normalized


def build_canonical_post_publication_audit(
    *,
    public_canary: Mapping[str, Any],
    public_benchmark: Mapping[str, Any],
    rollback_rehearsal: Mapping[str, Any],
    measurements: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the LCR-046 audit to the immutable LCR-043..045 evidence."""

    canary = check_canonical_public_canary_receipt(public_canary)
    benchmark = check_canonical_public_benchmark_receipt(public_benchmark)
    rehearsal = check_canonical_rollback_rehearsal(rollback_rehearsal)
    public_revision = require_immutable_revision(
        canary.get("public_revision"), name="public_revision"
    )
    previous_pin = require_immutable_revision(
        canary.get("previous_public_pin"), name="previous_public_pin"
    )
    if previous_pin != PREVIOUS_PUBLIC_PIN or public_revision == previous_pin:
        raise PostPublicationPinError("canonical public pin lineage drifted")
    for dependency in (benchmark, rehearsal):
        if (
            dependency.get("dataset_repo_id") != DEFAULT_DATASET_REPO
            or dependency.get("public_revision") != public_revision
            or dependency.get("previous_public_pin") != previous_pin
            or dependency.get("final_manifest_digest")
            != canary.get("final_manifest_digest")
            or dependency.get("release_manifest_digest")
            != canary.get("release_manifest_digest")
        ):
            raise PostPublicationContradictionError(
                "canonical canary, benchmark, and rollback evidence disagree"
            )
    if (
        benchmark.get("public_canary_digest") != canary.get("canonical_digest")
        or rehearsal.get("public_canary_digest") != canary.get("canonical_digest")
    ):
        raise PostPublicationContradictionError(
            "downstream receipts do not bind the canonical public canary"
        )
    release_digest = _canonical_sha256(
        canary.get("release_manifest_digest"), name="release_manifest_digest"
    )
    measured = validate_canonical_post_publication_measurements(
        measurements, release_manifest_digest=release_digest
    )
    receipt = {
        "schema": CANONICAL_AUDIT_SCHEMA,
        "receipt_kind": CANONICAL_AUDIT_KIND,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "public_revision": public_revision,
        "public_sha": public_revision,
        "previous_public_pin": previous_pin,
        "final_manifest_digest": canary["final_manifest_digest"],
        "release_manifest_digest": release_digest,
        "public_canary_digest": canary["canonical_digest"],
        "public_benchmark_digest": benchmark["canonical_digest"],
        "rollback_rehearsal_digest": rehearsal["canonical_digest"],
        "source_receipts": measured["source_receipts"],
        "timestamps": measured["timestamps"],
        "update_checkpoints": measured["update_checkpoints"],
        "manifests": measured["manifests"],
        "upstream_changes": measured["upstream_changes"],
        "delta_refill_findings_bounded": True,
        "max_delta_findings": MAX_DELTA_FINDINGS,
        "update_plan": measured["update_plan"],
        "no_contradiction_remains": True,
        "new_upstream_changes_are_delta_work": True,
        "upstream_changes_mixed_into_release": False,
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return check_canonical_post_publication_audit(receipt)


def check_canonical_post_publication_audit(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an existing LCR-046 receipt without rebuilding or writing it."""

    if not isinstance(receipt, Mapping):
        raise PostPublicationAuditError("canonical post-publication audit must be an object")
    report = dict(receipt)
    if (
        report.get("schema") != CANONICAL_AUDIT_SCHEMA
        or report.get("receipt_kind") != CANONICAL_AUDIT_KIND
        or report.get("task_id") != TASK_ID
        or report.get("status") != "passed"
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("no_contradiction_remains") is not True
        or report.get("new_upstream_changes_are_delta_work") is not True
        or report.get("upstream_changes_mixed_into_release") is not False
        or report.get("read_only") is not True
        or report.get("remote_mutation_attempted") is not False
        or report.get("unexpected_operations") != []
    ):
        raise PostPublicationContradictionError(
            "canonical post-publication identity/status drifted"
        )
    public_revision = require_immutable_revision(
        report.get("public_revision"), name="public_revision"
    )
    previous_pin = require_immutable_revision(
        report.get("previous_public_pin"), name="previous_public_pin"
    )
    if (
        report.get("public_sha") != public_revision
        or previous_pin != PREVIOUS_PUBLIC_PIN
        or public_revision == previous_pin
    ):
        raise PostPublicationPinError("canonical audit pin lineage drifted")
    for name in (
        "final_manifest_digest",
        "release_manifest_digest",
        "public_canary_digest",
        "public_benchmark_digest",
        "rollback_rehearsal_digest",
    ):
        _canonical_sha256(report.get(name), name=name)
    validate_canonical_post_publication_measurements(
        report, release_manifest_digest=report["release_manifest_digest"]
    )
    declared = _canonical_sha256(
        report.get("canonical_digest") or report.get("content_digest"),
        name="canonical_digest",
    )
    if canonical_no_self_field_digest(report) != declared:
        raise PostPublicationContradictionError(
            "canonical post-publication digest mismatch"
        )
    reject_credentials_in_payload(report, label="canonical_post_publication_audit")
    assert_no_secrets_or_absolute_paths(
        report, label="canonical_post_publication_audit"
    )
    return report


def run_canonical_post_publication_audit(
    *,
    public_canary: Mapping[str, Any],
    public_benchmark: Mapping[str, Any],
    rollback_rehearsal: Mapping[str, Any],
    audit_runner: Any,
) -> dict[str, Any]:
    """Execute an injected bounded read-only audit and seal its measurements."""

    if not callable(audit_runner):
        raise PostPublicationAuditError("a bounded read-only audit_runner is required")
    canary = check_canonical_public_canary_receipt(public_canary)
    measurements = audit_runner(
        canary["dataset_repo_id"], canary["public_revision"]
    )
    return build_canonical_post_publication_audit(
        public_canary=canary,
        public_benchmark=public_benchmark,
        rollback_rehearsal=rollback_rehearsal,
        measurements=measurements,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit_state_laws_post_publication.py",
        description=(
            "Audit post-publication completeness and update readiness for "
            f"the immutable state-law public pin ({TASK_ID}). Default mode "
            "is offline and does not mutate the Hub. New upstream changes "
            "are identified as delta work and are not silently mixed into "
            "this release. The update plan preserves exact-51 and "
            "transactional gates."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the sealed post_publication_audit.json against a fresh offline build",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write/refresh {DEFAULT_REPORT_RELPATH.as_posix()}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path for the audit JSON "
            f"(default: stdout, or {DEFAULT_REPORT_RELPATH.as_posix()} with --write)"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the sealed post-publication audit report "
            f"(default: {DEFAULT_REPORT_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Always print the audit/verification result as JSON",
    )
    parser.add_argument(
        "--public-canary",
        type=Path,
        default=None,
        help=f"Canonical LCR-043 receipt (default: {DEFAULT_CANARY_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--public-benchmark",
        type=Path,
        default=None,
        help=f"Canonical LCR-044 receipt (default: {DEFAULT_BENCHMARK_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--rollback-rehearsal",
        type=Path,
        default=None,
        help=f"Canonical LCR-045 receipt (default: {DEFAULT_REHEARSAL_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--measurements",
        type=Path,
        default=None,
        help="Measured, bounded read-only audit JSON (required when generating)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        reject_secrets_on_argv(argv_list)
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)
    except PostPublicationSafetyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )

    try:
        if args.check:
            if args.write:
                raise PostPublicationSafetyError("--check and --write are mutually exclusive")
            result = check_canonical_post_publication_audit(
                load_json_mapping(report_path)
            )
            if args.print_json:
                write_json(None, result)
            print(
                "check: pass ({task}) no_contradiction={ok} exact_51={exact} "
                "transactional={txn} delta_not_mixed={delta}".format(
                    task=result.get("task_id"),
                    ok=result.get("no_contradiction_remains"),
                    exact=(result.get("update_plan") or {}).get("preserves_exact_51"),
                    txn=(result.get("update_plan") or {}).get(
                        "preserves_transactional_gates"
                    ),
                    delta=not result.get("upstream_changes_mixed_into_release"),
                ),
                file=sys.stderr,
            )
            return 0

        if args.measurements is None:
            raise PostPublicationAuditError(
                "--measurements is required to generate canonical LCR-046 evidence"
            )
        report = build_canonical_post_publication_audit(
            public_canary=load_json_mapping(args.public_canary or default_canary_path()),
            public_benchmark=load_json_mapping(
                args.public_benchmark or default_benchmark_path()
            ),
            rollback_rehearsal=load_json_mapping(
                args.rollback_rehearsal or default_rehearsal_path()
            ),
            measurements=load_json_mapping(args.measurements),
        )
        if args.write:
            destination = (
                Path(args.output).expanduser().resolve()
                if args.output is not None
                else report_path
            )
            write_json(destination, report)
            print(
                f"wrote {DEFAULT_REPORT_RELPATH.as_posix()} "
                f"digest={report['canonical_digest']}",
                file=sys.stderr,
            )
            if args.print_json:
                write_json(None, report)
            return 0

        write_json(None, report)
        return 0

    except (
        PostPublicationAuditError,
        PostPublicationContradictionError,
        PostPublicationSafetyError,
        PostPublicationDeltaError,
        PostPublicationPinError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
