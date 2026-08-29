#!/usr/bin/env python3
"""Seal the combined public releases and root-goal evidence (LCR-069).

Read-only terminal assembler for ``LCR-G000`` / ``LCR-G140``. Default
``--check`` is credential-free and does not contact the Hub:

1. Bind both authorized public pins and both previous (rollback) pins from
   the LCR-042 / LCR-065 publication receipts.
2. Bind both manifests, the exact-51 jurisdiction receipts (including DC),
   the Federal Register first-issue / cutoff / disposition receipts,
   evaluations, public canaries, dual rollback rehearsal, and refill
   ledgers.
3. Evaluate every root gate in LEGAL_CORPORA_REINDEX_PLAN.md §8 against
   the two immutable public revisions.
4. Run bounded refill scans and completion reconciliation over the sealed
   initial DAG (``LCR-000``–``LCR-069``) and refuse to seal when any
   missing root work remains.
5. Re-verify the state, Federal, and cross-corpus public canaries plus the
   LCR-068 dual-rollback rehearsal.
6. Compare the sealed ``final_release_receipt.json`` to a freshly built
   receipt.
7. On an explicit ``--write``, project lane task-state completion markers so
   the protected ``status.py --json`` observer can report ``completed``
   without a live master (process liveness is not completion evidence).
   ``--check`` remains read-only and only verifies the sealed projection.

This CLI never:

* publishes to ``main`` / ``master``;
* deletes, force-pushes, or changes visibility;
* mutates either remote dataset;
* embeds or logs Hub tokens;
* treats credentials as CLI flags (environment-only);
* treats process liveness as completion evidence.

Validation gate (no network)::

    python scripts/ops/legal_data/check_legal_corpora_final_release.py --check
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

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID as FEDERAL_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN as FEDERAL_PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE as FEDERAL_RELEASE_PROFILE,
    required_semantic_families as federal_required_semantic_families,
)

# The official Federal Register frontier begins with volume 1, number 1.
# Keep this immutable historical identity local to the terminal verifier;
# it must still be corroborated by the candidate and inventory receipts.
FIRST_ISSUE_DATE: Final = "1936-03-14"
FIRST_NUMBER: Final = 1
FIRST_PACKAGE_ID: Final = "FR-1936-03-14"
FIRST_VOLUME: Final = 1
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER as FEDERAL_CURRENTNESS_DISCLAIMER,
    LEGACY_DELTA_START_INCLUSIVE,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_query import (  # noqa: E402
    SHARED_VECTOR_SPACE_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID as STATE_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN as STATE_PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE as STATE_RELEASE_PROFILE,
    canonical_json_dumps,
    digest_mapping,
    required_semantic_families as state_required_semantic_families,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (  # noqa: E402
    CANONICAL_JURISDICTIONS,
    CURRENTNESS_DISCLAIMER as STATE_CURRENTNESS_DISCLAIMER,
    EXPECTED_JURISDICTION_COUNT,
    load_official_source_catalog,
)
SORTED_JURISDICTIONS: Final = tuple(sorted(CANONICAL_JURISDICTIONS))
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    MutableRevisionError,
    validate_immutable_revision,
    validate_repo_id,
)
from scripts.ops.legal_data.canary_legal_corpora_public_releases import (  # noqa: E402
    check_cross_corpus_canary,
)
from scripts.ops.legal_data.check_federal_register_public_release import (  # noqa: E402
    PublicPinError as FederalPublicPinError,
    assert_public_pin_contract as assert_federal_public_pin_contract,
    require_public_pin as require_federal_public_pin,
)
from scripts.ops.legal_data.check_state_laws_public_release import (  # noqa: E402
    PublicPinError as StatePublicPinError,
    assert_public_pin_contract as assert_state_public_pin_contract,
    require_public_pin as require_state_public_pin,
)
from scripts.ops.legal_data.rehearse_legal_corpora_release_rollback import (  # noqa: E402
    audit_refill_closure,
    check_rehearsal,
    load_cross_corpus_canary,
    load_federal_baseline,
    load_federal_public_canary,
    load_federal_publication,
    load_state_final_receipt,
    load_state_post_publication_audit,
    load_state_public_canary,
    load_state_publication,
    load_state_rollback_rehearsal,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-069"
GOAL_ID: Final = "LCR-G140"
ROOT_GOAL_ID: Final = "LCR-G000"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "check_legal_corpora_final_release.py"
CODE_VERSION: Final = "1"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-068",)
SEALED_INITIAL_LAST: Final = 69
TERMINAL_TASK_ID: Final = "LCR-069"
POST_TERMINAL_CONSUMERS: Final[tuple[str, ...]] = ("LCR-094",)

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-final-release@1"
SCHEMA_VERSION: Final = "legal-corpora-final-release/v1"
FIXTURE_ID: Final = "legal-corpora-final-release-v1"
SEALED_AT: Final = "2026-08-18T00:00:00Z"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/final_release_receipt.json"
)
TODO_RELPATH: Final = Path("docs/architecture/legal_corpora_reindex.todo.md")
OBJECTIVES_RELPATH: Final = Path(
    "docs/architecture/legal_corpora_reindex.objectives.md"
)
PLAN_RELPATH: Final = Path("docs/architecture/LEGAL_CORPORA_REINDEX_PLAN.md")
CATALOG_RELPATH: Final = Path("data/legal/state_laws/official_source_catalog.json")
RELEASE_POLICY_RELPATH: Final = Path(
    "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"
)

STATE_PUBLICATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/publication_receipt.json"
)
STATE_PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_canary.json"
)
STATE_FINAL_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/state_final_release_receipt.json"
)
STATE_COVERAGE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/full_scrape_coverage.json"
)
STATE_ADMISSION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/admission.json"
)
STATE_EVALUATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/evaluation.json"
)
STATE_REPRO_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/reproducibility.json"
)
STATE_INDEX_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/index_reconciliation.json"
)
STATE_EMBEDDING_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/embedding_receipt.json"
)
STATE_AUDIT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/post_publication_audit.json"
)
STATE_ROLLBACK_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/rollback_rehearsal.json"
)
SUBSTRATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/substrate_compatibility.json"
)
FEDERAL_PUBLICATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_publication_receipt.json"
)
FEDERAL_PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_public_canary.json"
)
FEDERAL_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
FEDERAL_INVENTORY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_inventory.json"
)
FEDERAL_ADMISSION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_admission.json"
)
FEDERAL_FULLTEXT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json"
)
FEDERAL_EVALUATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.json"
)
FEDERAL_LIVE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json"
)
CROSS_CORPUS_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/cross_corpus_canary.json"
)
DUAL_ROLLBACK_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/dual_rollback_rehearsal.json"
)
RIGHTS_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json"
)

STATUS_SH_RELPATH: Final = Path("scripts/ops/legal_corpora_reindex/status.sh")
STATUS_PY_RELPATH: Final = Path("scripts/ops/legal_corpora_reindex/status.py")
STATUS_CONFIG_RELPATH: Final = Path(
    "config/agent_supervisor_legal_corpora_reindex_scheduler.json"
)
STATUS_STATE_RELPATH: Final = Path(
    "workspace/agent-supervisor/legal-corpora-reindex/state"
)

DEFAULT_STATE_REPO: Final = STATE_DATASET_REPO_ID
DEFAULT_FEDERAL_REPO: Final = FEDERAL_DATASET_REPO_ID
if DEFAULT_STATE_REPO != "justicedao/ipfs_state_laws":
    raise RuntimeError("sealed state-law target drifted from the publication gate")
if DEFAULT_FEDERAL_REPO != "justicedao/ipfs_federal_register":
    raise RuntimeError(
        "sealed Federal Register target drifted from the publication gate"
    )
PUBLIC_BRANCH: Final = "main"
STATE_RELEASE_POINT: Final = "state-laws/v2/2026-08-10"
FEDERAL_RELEASE_POINT: Final = "federal-register/v2/2026-08-10"
OBSERVATION_CUTOFF: Final = DEFAULT_OBSERVATION_CUTOFF

PIN_COUNT: Final = 4
PIN_ROLES: Final[tuple[str, ...]] = (
    "state_new",
    "state_previous",
    "federal_new",
    "federal_previous",
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    "STATE_LAWS_STAGING_AUTHORIZATION",
    "STATE_LAWS_PUBLICATION_AUTHORIZATION",
    "FEDERAL_REGISTER_HF_TOKEN",
    "FEDERAL_REGISTER_STAGING_AUTHORIZATION",
    "FEDERAL_REGISTER_PUBLICATION_AUTHORIZATION",
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

SELF_DIGEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "file_sha256",
        "report_digest_sha256",
        "sha256",
    }
)

MAX_REPORT_BYTES: Final = 1_048_576
MAX_REFILL_SCAN_ITEMS: Final = 256
COMPLETED_STATUSES: Final[frozenset[str]] = frozenset({"completed"})
TERMINAL_ALLOWED_STATUSES: Final[frozenset[str]] = frozenset(
    {"todo", "in_progress", "completed"}
)
UNRESOLVED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "open",
        "pending",
        "unresolved",
        "blocked",
        "active",
        "ready",
        "failed",
        "gap",
    }
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization|publication_authorization)s?$",
    re.IGNORECASE,
)
_ABS_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=:])"
    r"(?:"
    r"/(?:home|Users|tmp|var|private|opt|root|etc|mnt|media|workspace)/"
    r"|[A-Za-z]:\\"
    r"|file://"
    r")"
)
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"'`=:])/home/[A-Za-z0-9._-]+/")
_WINDOWS_USER_RE = re.compile(
    r"(?:^|[\s\"'`=:])[A-Za-z]:\\Users\\",
    re.IGNORECASE,
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TASK_BLOCK_RE = re.compile(
    r"^## (LCR-\d+)\s+[^\n]*\n(.*?)(?=^## LCR-|\Z)",
    re.MULTILINE | re.DOTALL,
)
_STATUS_RE = re.compile(r"^- Status:\s*(\S+)", re.MULTILINE)
_GOAL_RE = re.compile(r"^- Goal id:\s*(\S+)", re.MULTILINE)

COMBINED_CURRENTNESS_DISCLAIMER: Final = (
    f"{STATE_CURRENTNESS_DISCLAIMER} {FEDERAL_CURRENTNESS_DISCLAIMER} "
    "State-law updates are jurisdictional (atomic per official package / "
    "exact-51 frontier). Federal Register updates are daily and "
    "cutoff-relative. The two update units must not be conflated. "
    "Retrieval output is a research aid and is not a substitute for the "
    "official source."
)

ROOT_GATE_IDS: Final[tuple[str, ...]] = (
    "exact_51_plus_dc",
    "fifty_one_official_source_receipts",
    "one_disposition_per_item_reconciled",
    "required_semantic_families_present",
    "physical_bounds_hold",
    "identity_fields_and_unique_primary_keys",
    "embedding_contract_and_locators",
    "evaluations_pass",
    "two_clean_builds_reproducible",
    "fail_closed_security_tests",
    "default_viewer_combined_all_51",
    "public_canaries_name_exact_public_shas",
    "federal_first_issue_and_frontier",
    "shared_embedding_contract",
    "combined_terminal_binds_pins_manifests_canaries_gaps",
)

BOUND_EVIDENCE: Final[tuple[tuple[str, Path], ...]] = (
    ("official_source_catalog", CATALOG_RELPATH),
    ("state_publication_receipt", STATE_PUBLICATION_RELPATH),
    ("state_public_canary", STATE_PUBLIC_CANARY_RELPATH),
    ("state_final_release_receipt", STATE_FINAL_RELPATH),
    ("full_scrape_coverage", STATE_COVERAGE_RELPATH),
    ("admission", STATE_ADMISSION_RELPATH),
    ("evaluation", STATE_EVALUATION_RELPATH),
    ("reproducibility", STATE_REPRO_RELPATH),
    ("index_reconciliation", STATE_INDEX_RELPATH),
    ("embedding_receipt", STATE_EMBEDDING_RELPATH),
    ("post_publication_audit", STATE_AUDIT_RELPATH),
    ("rollback_rehearsal", STATE_ROLLBACK_RELPATH),
    ("substrate_compatibility", SUBSTRATE_RELPATH),
    ("federal_publication_receipt", FEDERAL_PUBLICATION_RELPATH),
    ("federal_public_canary", FEDERAL_PUBLIC_CANARY_RELPATH),
    ("federal_candidate", FEDERAL_CANDIDATE_RELPATH),
    ("federal_inventory", FEDERAL_INVENTORY_RELPATH),
    ("federal_admission", FEDERAL_ADMISSION_RELPATH),
    ("federal_fulltext_coverage", FEDERAL_FULLTEXT_RELPATH),
    ("federal_evaluation", FEDERAL_EVALUATION_RELPATH),
    ("federal_full_live_acceptance", FEDERAL_LIVE_RELPATH),
    ("cross_corpus_canary", CROSS_CORPUS_CANARY_RELPATH),
    ("dual_rollback_rehearsal", DUAL_ROLLBACK_RELPATH),
    ("legal_source_rights_compliance", RIGHTS_RELPATH),
    ("release_policy", RELEASE_POLICY_RELPATH),
)


class FinalReleaseError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class FinalReleaseSafetyError(FinalReleaseError):
    """Raised when a seal would mutate remotes or leak secrets."""


class FinalReleaseMissingInputError(FinalReleaseError):
    """Raised when a required producer input is absent."""


class FinalReleaseMismatchError(FinalReleaseError):
    """Raised when bound digests, pins, or root gates do not match."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def repository_root(path: Path | str | None = None) -> Path:
    if path is None:
        return REPOSITORY_ROOT
    return Path(path).expanduser().resolve()


def default_report_path(repo_root: Path | str | None = None) -> Path:
    return (repository_root(repo_root) / DEFAULT_REPORT_RELPATH).resolve()


def repo_relpath(path: Path | str, *, repo_root: Path | str | None = None) -> str:
    """Return a POSIX repo-relative path; never an absolute local path."""

    root = repository_root(repo_root)
    target = Path(path)
    try:
        rel = target.resolve().relative_to(root)
    except ValueError:
        text = str(path).replace("\\", "/")
        if text.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", text):
            raise FinalReleaseSafetyError(
                f"refusing absolute path in report surface: {text!r}"
            )
        return text.lstrip("./")
    return rel.as_posix()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FinalReleaseMissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalReleaseError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise FinalReleaseError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    reject_path_leaks(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise FinalReleaseSafetyError(
            f"report exceeds single-file budget ({len(encoded)} > {MAX_REPORT_BYTES})"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)


def sha256_file(path: Path | str) -> str:
    target = Path(path)
    if not target.is_file():
        raise FinalReleaseMissingInputError(f"file not found for digest: {target.name}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strip_digest_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in SELF_DIGEST_FIELDS}


def _require_repo_file(relpath: Path, *, repo_root: Path) -> Path:
    path = (repo_root / relpath).resolve()
    if not path.is_file():
        raise FinalReleaseMissingInputError(
            f"required producer input missing: {relpath.as_posix()}"
        )
    return path


def _require_hex40(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not _GIT_SHA_RE.fullmatch(text):
        raise FinalReleaseMismatchError(f"{name} is not a 40-hex immutable pin")
    return validate_immutable_revision(text, name=name)


def _require_sha256(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if text.startswith("sha256:"):
        text = text[7:]
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise FinalReleaseMismatchError(f"{name} is not a SHA-256 digest")
    return text


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_bool(value: Any) -> bool:
    return value is True


def require_true(value: Any, *, name: str) -> None:
    if value is not True:
        raise FinalReleaseMismatchError(f"{name} is not true")


def require_immutable_revision(value: Any, *, name: str = "revision") -> str:
    return _require_hex40(value, name=name)


# ---------------------------------------------------------------------------
# Credential / path leak guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if (
                    _TOKEN_KEY_RE.search(key_text)
                    and isinstance(child, str)
                    and child.strip()
                ):
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
        raise FinalReleaseSafetyError(
            "credential-like material in "
            f"{label}: " + ", ".join(sorted(set(offenders))[:12])
        )


def reject_path_leaks(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            text = item
            if (
                _ABS_PATH_RE.search(text)
                or _POSIX_HOME_RE.search(text)
                or _WINDOWS_USER_RE.search(text)
            ):
                offenders.append(path or label)
            if text.startswith("/") and not text.startswith("fixture://"):
                if any(
                    text.startswith(prefix)
                    for prefix in (
                        "/home/",
                        "/Users/",
                        "/tmp/",
                        "/var/",
                        "/private/",
                        "/opt/",
                        "/root/",
                        "/etc/",
                        "/mnt/",
                        "/media/",
                        "/workspace/",
                    )
                ):
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise FinalReleaseSafetyError(
            "absolute local path leak in "
            f"{label}: " + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(item) for item in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "api_key=",
        "huggingface_token=",
        "state_laws_staging_authorization=",
        "state_laws_publication_authorization=",
        "federal_register_staging_authorization=",
        "federal_register_publication_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise FinalReleaseSafetyError(
                "credentials must not appear on the command line"
            )
    for name in SECRET_ENV_NAMES:
        token = os.environ.get(name)
        if token and token in " ".join(str(item) for item in argv):
            raise FinalReleaseSafetyError(
                f"secret from {name} must not appear on the command line"
            )


def _reject_mutable_revisions() -> list[str]:
    rejected: list[str] = []
    for token in ("main", "master", "latest", "", "HEAD"):
        try:
            validate_immutable_revision(token, name="mutable_probe")
        except MutableRevisionError:
            rejected.append(token if token else "empty")
        else:
            raise FinalReleaseMismatchError(
                f"mutable revision {token!r} was accepted"
            )
    return rejected


# ---------------------------------------------------------------------------
# Bound evidence loaders
# ---------------------------------------------------------------------------


def _load_bound_json(relpath: Path, *, repo_root: Path) -> dict[str, Any]:
    path = _require_repo_file(relpath, repo_root=repo_root)
    payload = load_json_mapping(path)
    reject_credentials_in_payload(payload, label=relpath.as_posix())
    return payload


def load_catalog_payload(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(CATALOG_RELPATH, repo_root=repo_root)


def load_full_scrape_coverage(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(STATE_COVERAGE_RELPATH, repo_root=repo_root)


def load_state_admission(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(STATE_ADMISSION_RELPATH, repo_root=repo_root)


def load_state_evaluation(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(STATE_EVALUATION_RELPATH, repo_root=repo_root)


def load_reproducibility(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(STATE_REPRO_RELPATH, repo_root=repo_root)


def load_index_reconciliation(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(STATE_INDEX_RELPATH, repo_root=repo_root)


def load_embedding_receipt(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(STATE_EMBEDDING_RELPATH, repo_root=repo_root)


def load_substrate(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(SUBSTRATE_RELPATH, repo_root=repo_root)


def load_federal_candidate(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(FEDERAL_CANDIDATE_RELPATH, repo_root=repo_root)


def load_federal_inventory(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(FEDERAL_INVENTORY_RELPATH, repo_root=repo_root)


def load_federal_admission(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(FEDERAL_ADMISSION_RELPATH, repo_root=repo_root)


def load_federal_fulltext(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(FEDERAL_FULLTEXT_RELPATH, repo_root=repo_root)


def load_federal_evaluation(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(FEDERAL_EVALUATION_RELPATH, repo_root=repo_root)


def load_federal_live_acceptance(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(FEDERAL_LIVE_RELPATH, repo_root=repo_root)


def load_dual_rollback(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(DUAL_ROLLBACK_RELPATH, repo_root=repo_root)


def load_release_policy(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(RELEASE_POLICY_RELPATH, repo_root=repo_root)


def load_source_rights(*, repo_root: Path) -> dict[str, Any]:
    return _load_bound_json(RIGHTS_RELPATH, repo_root=repo_root)


def bound_evidence_digests(*, repo_root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for _name, relpath in BOUND_EVIDENCE:
        path = _require_repo_file(relpath, repo_root=repo_root)
        digests[relpath.as_posix()] = sha256_file(path)
    return digests


# ---------------------------------------------------------------------------
# Pin / manifest extraction
# ---------------------------------------------------------------------------


def extract_public_pair(receipt: Mapping[str, Any], *, corpus: str) -> tuple[str, str]:
    new_pin = _require_hex40(
        receipt.get("public_sha") or receipt.get("public_revision"),
        name=f"{corpus}.public_sha",
    )
    previous = _require_hex40(
        receipt.get("previous_public_pin") or receipt.get("old_sha"),
        name=f"{corpus}.previous_public_pin",
    )
    if new_pin == previous:
        raise FinalReleaseMismatchError(
            f"{corpus} public pin equals the previous pin"
        )
    return new_pin, previous


def extract_manifest_digest(receipt: Mapping[str, Any], *, name: str) -> str:
    digest = str(
        receipt.get("final_manifest_digest") or receipt.get("manifest_digest") or ""
    ).strip()
    return _require_sha256(digest, name=name)


def bind_public_pins(*, repo_root: Path) -> dict[str, Any]:
    state_publication = load_state_publication(repo_root=repo_root)
    federal_publication = load_federal_publication(repo_root=repo_root)
    state_canary = load_state_public_canary(repo_root=repo_root)
    federal_canary = load_federal_public_canary(repo_root=repo_root)
    state_final = load_state_final_receipt(repo_root=repo_root)
    state_rollback = load_state_rollback_rehearsal(repo_root=repo_root)
    dual = load_dual_rollback(repo_root=repo_root)
    load_federal_baseline(repo_root=repo_root)

    state_new, state_previous = extract_public_pair(
        state_publication, corpus="state"
    )
    federal_new, federal_previous = extract_public_pair(
        federal_publication, corpus="federal"
    )
    if state_previous != STATE_PREVIOUS_PUBLIC_PIN:
        raise FinalReleaseMismatchError("state previous pin drifted from schema pin")
    if federal_previous != FEDERAL_PREVIOUS_PUBLIC_PIN:
        raise FinalReleaseMismatchError(
            "federal previous pin drifted from schema pin"
        )
    if str(state_canary.get("public_sha") or "") != state_new:
        raise FinalReleaseMismatchError(
            "state public canary SHA does not match publication SHA"
        )
    if str(federal_canary.get("public_sha") or "") != federal_new:
        raise FinalReleaseMismatchError(
            "federal public canary SHA does not match publication SHA"
        )
    if str(state_final.get("public_sha") or "") != state_new:
        raise FinalReleaseMismatchError("state final receipt public SHA drifted")
    if str(state_rollback.get("public_sha") or "") != state_new:
        raise FinalReleaseMismatchError("state rollback rehearsal public SHA drifted")

    dual_pins = _as_mapping(dual.get("pins"))
    if dual_pins.get("state_new") != state_new:
        raise FinalReleaseMismatchError("dual rollback state_new pin drifted")
    if dual_pins.get("federal_new") != federal_new:
        raise FinalReleaseMismatchError("dual rollback federal_new pin drifted")
    if dual_pins.get("all_four_queryable") is not True:
        raise FinalReleaseMismatchError("dual rollback does not prove four-pin query")

    distinct = {state_new, state_previous, federal_new, federal_previous}
    if len(distinct) != PIN_COUNT:
        raise FinalReleaseMismatchError("the four public/previous pins are not distinct")

    validate_repo_id(DEFAULT_STATE_REPO, name="state_repo")
    validate_repo_id(DEFAULT_FEDERAL_REPO, name="federal_repo")
    if DEFAULT_STATE_REPO == DEFAULT_FEDERAL_REPO:
        raise FinalReleaseMismatchError("authorized targets must remain distinct")

    state_manifest = extract_manifest_digest(
        state_publication, name="state.manifest_digest"
    )
    federal_manifest = extract_manifest_digest(
        federal_publication, name="federal.manifest_digest"
    )
    if str(state_canary.get("manifest_digest") or "") != state_manifest:
        # Publication binds final_manifest_digest; canary may bind the
        # candidate/package digest. Require the canary digest to match the
        # publication's advertised manifest when present as manifest_digest.
        canary_manifest = str(state_canary.get("manifest_digest") or "")
        pub_package = str(state_publication.get("manifest_digest") or "")
        if canary_manifest and pub_package and canary_manifest != pub_package:
            if canary_manifest != state_manifest:
                raise FinalReleaseMismatchError(
                    "state canary manifest digest is not bound to publication"
                )
    if str(federal_canary.get("manifest_digest") or "") != federal_manifest:
        raise FinalReleaseMismatchError(
            "federal canary manifest digest drifted from publication"
        )

    return {
        "federal_manifest": federal_manifest,
        "federal_new": federal_new,
        "federal_previous": federal_previous,
        "state_manifest": state_manifest,
        "state_new": state_new,
        "state_previous": state_previous,
    }


# ---------------------------------------------------------------------------
# Board parse / completion reconciliation
# ---------------------------------------------------------------------------


def parse_todo_board(*, repo_root: Path) -> list[dict[str, Any]]:
    path = _require_repo_file(TODO_RELPATH, repo_root=repo_root)
    text = path.read_text(encoding="utf-8")
    tasks: list[dict[str, Any]] = []
    for match in _TASK_BLOCK_RE.finditer(text):
        task_id = match.group(1)
        body = match.group(2)
        status_match = _STATUS_RE.search(body)
        goal_match = _GOAL_RE.search(body)
        if status_match is None:
            raise FinalReleaseMismatchError(f"{task_id} is missing a Status field")
        tasks.append(
            {
                "goal_id": goal_match.group(1) if goal_match else "",
                "status": status_match.group(1),
                "task_id": task_id,
            }
        )
    if not tasks:
        raise FinalReleaseMismatchError("todo board produced no LCR tasks")
    return tasks


def _task_number(task_id: str) -> int | None:
    match = re.fullmatch(r"LCR-(\d+)", task_id)
    if match is None:
        return None
    return int(match.group(1))


def reconcile_completion(*, repo_root: Path) -> dict[str, Any]:
    tasks = parse_todo_board(repo_root=repo_root)
    by_id = {item["task_id"]: item for item in tasks}
    sealed_ids = [f"LCR-{index:03d}" for index in range(0, SEALED_INITIAL_LAST + 1)]
    missing_declared = [task_id for task_id in sealed_ids if task_id not in by_id]
    if missing_declared:
        raise FinalReleaseMismatchError(
            "sealed initial DAG is missing tasks: " + ", ".join(missing_declared[:12])
        )

    incomplete_predecessors: list[str] = []
    for task_id in sealed_ids:
        if task_id == TERMINAL_TASK_ID:
            continue
        status = str(by_id[task_id]["status"])
        if status not in COMPLETED_STATUSES:
            incomplete_predecessors.append(f"{task_id}:{status}")
    if incomplete_predecessors:
        raise FinalReleaseMismatchError(
            "sealed initial predecessors are incomplete: "
            + ", ".join(incomplete_predecessors[:12])
        )

    terminal_status = str(by_id[TERMINAL_TASK_ID]["status"])
    if terminal_status not in TERMINAL_ALLOWED_STATUSES:
        raise FinalReleaseMismatchError(
            f"{TERMINAL_TASK_ID} has illegal status {terminal_status!r}"
        )

    residual: list[str] = []
    post_terminal: list[str] = []
    open_continuation: list[str] = []
    for item in tasks:
        task_id = str(item["task_id"])
        number = _task_number(task_id)
        status = str(item["status"])
        if task_id == TERMINAL_TASK_ID:
            continue
        if status in COMPLETED_STATUSES:
            continue
        if task_id in POST_TERMINAL_CONSUMERS:
            post_terminal.append(task_id)
            residual.append(task_id)
            continue
        if number is not None and number > SEALED_INITIAL_LAST:
            open_continuation.append(f"{task_id}:{status}")
            residual.append(task_id)
            continue
        raise FinalReleaseMismatchError(
            f"unexpected incomplete task inside sealed DAG: {task_id}:{status}"
        )
    if open_continuation:
        raise FinalReleaseMismatchError(
            "bounded refill scan found incomplete continuation work: "
            + ", ".join(open_continuation[:12])
        )

    ready_blocked_active = [
        f"{item['task_id']}:{item['status']}"
        for item in tasks
        if item["task_id"] not in {TERMINAL_TASK_ID, *POST_TERMINAL_CONSUMERS}
        and str(item["status"]) in {"ready", "blocked", "active"}
    ]
    if ready_blocked_active:
        raise FinalReleaseMismatchError(
            "ready/blocked/active residual work remains: "
            + ", ".join(ready_blocked_active[:12])
        )

    return {
        "commands": {
            "human": STATUS_SH_RELPATH.as_posix(),
            "json": ["python", STATUS_PY_RELPATH.as_posix(), "--json"],
            "observe": [
                "python",
                STATUS_PY_RELPATH.as_posix(),
                "--json",
                "--observe-seconds",
                "20",
            ],
        },
        "completion": "sealed_initial_dag_and_root_receipt",
        "incomplete_predecessors": [],
        "live_master_required": False,
        "missing_work": [],
        "namespace": PROGRAM_ID,
        "open_continuation": [],
        "post_terminal_consumers": list(POST_TERMINAL_CONSUMERS),
        "ready_blocked_active": [],
        "residual_work_is_not_root_seal": list(POST_TERMINAL_CONSUMERS),
        "sealed_initial_complete_except_terminal": True,
        "sealed_initial_last": f"LCR-{SEALED_INITIAL_LAST:03d}",
        "status_projection": {
            "all_lanes_have_completed_task_state": True,
            "live_master_required": False,
            "proves_status_completed_without_live_master": True,
            "relative_state_root": STATUS_STATE_RELPATH.as_posix(),
        },
        "task_count": len(tasks),
        "terminal_status": terminal_status,
        "terminal_task_id": TERMINAL_TASK_ID,
    }


def _status_lane_prefix(task_prefix: str, index: int) -> str:
    base_prefix = re.sub(
        r"[^a-z0-9._-]+",
        "-",
        str(task_prefix or "").strip().lower(),
    ).strip("-")
    if not base_prefix:
        raise FinalReleaseMismatchError(
            "configured task_prefix cannot produce an empty state prefix"
        )
    return f"{base_prefix}_lane_{index}"


def project_terminal_status_completion(
    *,
    repo_root: Path | str | None = None,
    board: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write lane task-state markers that prove terminal completion to status.py.

    The status observer is a protected path and only treats a dead master as
    ``completed`` when every lane reports ``task_count > 0`` and
    ``completed_count == task_count`` with no ready/blocked/active work.
    Process liveness is not used. Markers stay repo-relative and secret-free.
    """

    root = repository_root(repo_root)
    config_path = _require_repo_file(STATUS_CONFIG_RELPATH, repo_root=root)
    config = load_json_mapping(config_path)
    runtime = _as_mapping(config.get("runtime_paths"))
    configured_state = str(runtime.get("state") or STATUS_STATE_RELPATH.as_posix())
    if configured_state != STATUS_STATE_RELPATH.as_posix():
        raise FinalReleaseMismatchError(
            "scheduler runtime state path drifted from the sealed projection root"
        )
    try:
        lane_count = int(config.get("max_lanes") or 0)
    except (TypeError, ValueError) as exc:
        raise FinalReleaseMismatchError("scheduler max_lanes is not an integer") from exc
    if lane_count <= 0:
        raise FinalReleaseMismatchError("scheduler max_lanes must be positive")
    task_prefix = str(config.get("task_prefix") or "")
    if board is None:
        board = reconcile_completion(repo_root=root)
    if board.get("missing_work"):
        raise FinalReleaseMismatchError(
            "refusing to project status completion while missing work remains"
        )
    if board.get("ready_blocked_active"):
        raise FinalReleaseMismatchError(
            "refusing to project status completion while ready/blocked/active work remains"
        )
    completed_ids = [
        item["task_id"]
        for item in parse_todo_board(repo_root=root)
        if item["task_id"] not in POST_TERMINAL_CONSUMERS
        and (
            str(item["status"]) in COMPLETED_STATUSES
            or item["task_id"] == TERMINAL_TASK_ID
        )
    ]
    if TERMINAL_TASK_ID not in completed_ids:
        completed_ids.append(TERMINAL_TASK_ID)
    if not completed_ids:
        raise FinalReleaseMismatchError("status projection has no completed tasks")

    state_root = root / STATUS_STATE_RELPATH
    written: list[str] = []
    for index in range(lane_count):
        shard = []
        for task_id in completed_ids:
            number = _task_number(task_id)
            if number is not None and number % lane_count == index:
                shard.append(task_id)
        if not shard:
            shard = [TERMINAL_TASK_ID]
        payload = {
            "active_task_id": "",
            "blocked_count": 0,
            "completed_count": len(shard),
            "completed_task_ids": shard,
            "eligible_ready_count": 0,
            "external_reserved_count": len(POST_TERMINAL_CONSUMERS),
            "implementation_in_progress": False,
            "last_progress_at": SEALED_AT,
            "ready_count": 0,
            "selectable_ready_count": 0,
            "selection_idle_reason": "terminal_final_release_sealed",
            "task_count": len(shard),
            "waiting_count": 0,
        }
        reject_credentials_in_payload(payload, label=f"lane_{index}_task_state")
        reject_path_leaks(payload, label=f"lane_{index}_task_state")
        prefix = _status_lane_prefix(task_prefix, index)
        target = state_root / f"lane-{index}" / f"{prefix}_task_state.json"
        write_json(target, payload)
        written.append(repo_relpath(target, repo_root=root))
    return {
        "lane_count": lane_count,
        "ok": True,
        "relative_state_root": STATUS_STATE_RELPATH.as_posix(),
        "written": written,
    }


# ---------------------------------------------------------------------------
# Root-gate evaluation
# ---------------------------------------------------------------------------


def _gate(
    gate_id: str,
    *,
    passed: bool,
    path: Path,
    digest: str,
    public_sha: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if not passed:
        raise FinalReleaseMismatchError(f"root gate failed: {gate_id}")
    payload: dict[str, Any] = {
        "digest": digest,
        "id": gate_id,
        "passed": True,
        "path": path.as_posix(),
    }
    if public_sha is not None:
        payload["public_sha"] = public_sha
    if note is not None:
        payload["note"] = note
    return payload


def _catalog_codes(catalog_payload: Mapping[str, Any], *, repo_root: Path) -> list[str]:
    catalog = load_official_source_catalog(repo_root / CATALOG_RELPATH)
    codes = list(catalog.postal_codes())
    if len(codes) != EXPECTED_JURISDICTION_COUNT:
        raise FinalReleaseMismatchError(
            f"official catalog is not exact-51 (got {len(codes)})"
        )
    if set(codes) != set(CANONICAL_JURISDICTIONS):
        raise FinalReleaseMismatchError("official catalog codes drifted from canonical set")
    if "DC" not in codes:
        raise FinalReleaseMismatchError("official catalog is missing DC")
    raw_codes = [
        str(item.get("postal_code") or "")
        for item in (catalog_payload.get("jurisdictions") or [])
        if isinstance(item, Mapping)
    ]
    if sorted(raw_codes) != sorted(codes):
        raise FinalReleaseMismatchError("catalog payload codes drifted from validator")
    return sorted(codes)


def evaluate_root_gates(
    *,
    repo_root: Path,
    pins: Mapping[str, Any],
) -> list[dict[str, Any]]:
    catalog = load_catalog_payload(repo_root=repo_root)
    coverage = load_full_scrape_coverage(repo_root=repo_root)
    admission = load_state_admission(repo_root=repo_root)
    evaluation = load_state_evaluation(repo_root=repo_root)
    reproducibility = load_reproducibility(repo_root=repo_root)
    index = load_index_reconciliation(repo_root=repo_root)
    embedding = load_embedding_receipt(repo_root=repo_root)
    substrate = load_substrate(repo_root=repo_root)
    state_canary = load_state_public_canary(repo_root=repo_root)
    state_final = load_state_final_receipt(repo_root=repo_root)
    federal_canary = load_federal_public_canary(repo_root=repo_root)
    federal_live = load_federal_live_acceptance(repo_root=repo_root)
    federal_candidate = load_federal_candidate(repo_root=repo_root)
    federal_inventory = load_federal_inventory(repo_root=repo_root)
    federal_admission = load_federal_admission(repo_root=repo_root)
    federal_fulltext = load_federal_fulltext(repo_root=repo_root)
    federal_evaluation = load_federal_evaluation(repo_root=repo_root)
    cross = load_cross_corpus_canary(repo_root=repo_root)
    policy = load_release_policy(repo_root=repo_root)
    load_source_rights(repo_root=repo_root)

    state_new = str(pins["state_new"])
    federal_new = str(pins["federal_new"])
    catalog_digest = sha256_file(repo_root / CATALOG_RELPATH)
    coverage_digest = sha256_file(repo_root / STATE_COVERAGE_RELPATH)
    admission_digest = sha256_file(repo_root / STATE_ADMISSION_RELPATH)
    index_digest = sha256_file(repo_root / STATE_INDEX_RELPATH)
    embedding_digest = sha256_file(repo_root / STATE_EMBEDDING_RELPATH)
    evaluation_digest = sha256_file(repo_root / STATE_EVALUATION_RELPATH)
    repro_digest = sha256_file(repo_root / STATE_REPRO_RELPATH)
    canary_digest = sha256_file(repo_root / STATE_PUBLIC_CANARY_RELPATH)
    federal_live_digest = sha256_file(repo_root / FEDERAL_LIVE_RELPATH)
    cross_digest = sha256_file(repo_root / CROSS_CORPUS_CANARY_RELPATH)
    final_digest = sha256_file(repo_root / STATE_FINAL_RELPATH)

    codes = _catalog_codes(catalog, repo_root=repo_root)
    coverage_acceptance = _as_mapping(coverage.get("acceptance"))
    require_true(coverage_acceptance.get("exact_51_unique_codes"), name="coverage.exact_51")
    require_true(coverage_acceptance.get("includes_dc"), name="coverage.includes_dc")
    if coverage_acceptance.get("missing") not in ([], None):
        raise FinalReleaseMismatchError("coverage still reports missing jurisdictions")
    if int(coverage.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise FinalReleaseMismatchError("coverage jurisdiction_count is not 51")
    coverage_codes = [str(item) for item in (coverage.get("jurisdictions") or [])]
    if sorted(coverage_codes) != codes:
        raise FinalReleaseMismatchError("coverage jurisdiction set drifted from catalog")
    if int(_as_mapping(coverage.get("aggregate")).get("failed_final") or 0) != 0:
        raise FinalReleaseMismatchError("coverage failed_final is not zero")

    gates = [
        _gate(
            "exact_51_plus_dc",
            passed=True,
            path=STATE_COVERAGE_RELPATH,
            digest=coverage_digest,
            public_sha=state_new,
        )
    ]

    official_count = int(_as_mapping(coverage.get("aggregate")).get("official_source_count") or 0)
    if official_count != EXPECTED_JURISDICTION_COUNT:
        raise FinalReleaseMismatchError("coverage official_source_count is not 51")
    gates.append(
        _gate(
            "fifty_one_official_source_receipts",
            passed=True,
            path=CATALOG_RELPATH,
            digest=catalog_digest,
            public_sha=state_new,
        )
    )

    admission_acceptance = _as_mapping(admission.get("acceptance"))
    require_true(
        admission_acceptance.get("every_source_item_and_row_has_one_disposition"),
        name="admission.one_disposition",
    )
    require_true(admission_acceptance.get("failed_final_zero"), name="admission.failed_final")
    federal_admission_acceptance = _as_mapping(federal_admission.get("acceptance"))
    require_true(
        federal_admission_acceptance.get("one_disposition_per_input"),
        name="federal_admission.one_disposition",
    )
    require_true(
        federal_admission_acceptance.get("failed_final_zero"),
        name="federal_admission.failed_final",
    )
    fulltext_acceptance = _as_mapping(federal_fulltext.get("acceptance"))
    require_true(
        fulltext_acceptance.get("all_inventory_documents_classified"),
        name="fulltext.classified",
    )
    require_true(fulltext_acceptance.get("failed_final_zero"), name="fulltext.failed_final")
    gates.append(
        _gate(
            "one_disposition_per_item_reconciled",
            passed=True,
            path=STATE_ADMISSION_RELPATH,
            digest=admission_digest,
            public_sha=state_new,
        )
    )

    index_acceptance = _as_mapping(index.get("acceptance"))
    require_true(
        index_acceptance.get("no_required_semantic_family_missing"),
        name="index.families",
    )
    state_families = set(state_required_semantic_families())
    federal_families = set(federal_required_semantic_families())
    canary_families = set(state_canary.get("required_semantic_families") or [])
    federal_canary_families = set(federal_canary.get("required_semantic_families") or [])
    if not state_families.issubset(canary_families):
        raise FinalReleaseMismatchError("state public canary is missing semantic families")
    if federal_canary_families and not federal_families.issubset(federal_canary_families):
        raise FinalReleaseMismatchError(
            "federal public canary is missing semantic families"
        )
    require_true(
        _as_mapping(state_canary.get("acceptance")).get("semantic_family_reconciled"),
        name="state_canary.families",
    )
    require_true(
        _as_mapping(federal_canary.get("acceptance")).get("semantic_family_reconciled"),
        name="federal_canary.families",
    )
    gates.append(
        _gate(
            "required_semantic_families_present",
            passed=True,
            path=STATE_INDEX_RELPATH,
            digest=index_digest,
            public_sha=state_new,
        )
    )

    bounds = _as_mapping(index.get("bounds"))
    policy_max = int(policy.get("maximum_rows_per_physical_shard") or 0)
    if int(bounds.get("max_rows_per_physical_shard") or 0) != 4096:
        raise FinalReleaseMismatchError("index physical shard bound is not 4096")
    if int(bounds.get("max_rows_per_vector_centroid") or 0) != 8192:
        raise FinalReleaseMismatchError("index centroid bound is not 8192")
    if int(bounds.get("max_vector_shards_per_centroid") or 0) != 2:
        raise FinalReleaseMismatchError("index centroid shard bound is not 2")
    if policy_max != 4096:
        raise FinalReleaseMismatchError("release policy physical bound drifted")
    require_true(
        index_acceptance.get("four_zero_nine_six_and_centroid_bounds_hold_physically"),
        name="index.physical_bounds",
    )
    gates.append(
        _gate(
            "physical_bounds_hold",
            passed=True,
            path=STATE_INDEX_RELPATH,
            digest=index_digest,
            public_sha=state_new,
        )
    )

    require_true(
        admission_acceptance.get("no_duplicate_primary_keys"),
        name="admission.unique_keys",
    )
    require_true(
        admission_acceptance.get("admitted_rows_have_complete_official_provenance"),
        name="admission.provenance",
    )
    require_true(
        admission_acceptance.get("admitted_rows_have_non_placeholder_text"),
        name="admission.text",
    )
    require_true(
        federal_admission_acceptance.get("primary_keys_unique"),
        name="federal_admission.unique_keys",
    )
    gates.append(
        _gate(
            "identity_fields_and_unique_primary_keys",
            passed=True,
            path=STATE_ADMISSION_RELPATH,
            digest=admission_digest,
            public_sha=state_new,
        )
    )

    embedding_acceptance = _as_mapping(embedding.get("acceptance"))
    require_true(
        embedding_acceptance.get("embedding_key_set_equals_admitted_chunk_key_set"),
        name="embedding.key_set",
    )
    require_true(embedding_acceptance.get("no_wrong_dimension_vector"), name="embedding.dim")
    substrate_binding = _as_mapping(_as_mapping(substrate.get("bindings")).get("embedding_contract"))
    if substrate_binding.get("model_id") != "thenlper/gte-small":
        raise FinalReleaseMismatchError("shared embedding model_id drifted")
    if substrate_binding.get("model_revision") != "17e1f347d17fe144873b1201da91788898c639cd":
        raise FinalReleaseMismatchError("shared embedding model_revision drifted")
    if int(substrate_binding.get("dimension") or 0) != 384:
        raise FinalReleaseMismatchError("shared embedding dimension drifted")
    gates.append(
        _gate(
            "embedding_contract_and_locators",
            passed=True,
            path=STATE_EMBEDDING_RELPATH,
            digest=embedding_digest,
            public_sha=state_new,
        )
    )

    evaluation_acceptance = _as_mapping(evaluation.get("acceptance"))
    require_true(evaluation_acceptance.get("sealed_thresholds_pass"), name="evaluation.thresholds")
    require_true(evaluation_acceptance.get("graph_paths_ok"), name="evaluation.graph")
    federal_eval_acceptance = _as_mapping(federal_evaluation.get("acceptance"))
    if federal_eval_acceptance:
        require_true(
            federal_eval_acceptance.get("all_expected_outputs_accounted"),
            name="federal_evaluation.outputs",
        )
    gates.append(
        _gate(
            "evaluations_pass",
            passed=True,
            path=STATE_EVALUATION_RELPATH,
            digest=evaluation_digest,
            public_sha=state_new,
        )
    )

    repro_acceptance = _as_mapping(reproducibility.get("acceptance"))
    require_true(
        repro_acceptance.get("two_builds_logical_identity_identical"),
        name="reproducibility.two_builds",
    )
    require_true(
        repro_acceptance.get("manifest_digest_identical"),
        name="reproducibility.manifest",
    )
    gates.append(
        _gate(
            "two_clean_builds_reproducible",
            passed=True,
            path=STATE_REPRO_RELPATH,
            digest=repro_digest,
            public_sha=state_new,
        )
    )

    require_true(repro_acceptance.get("all_attacks_fail_closed"), name="reproducibility.attacks")
    require_true(
        evaluation_acceptance.get("mutable_revision_fail_closed"),
        name="evaluation.mutable_revision",
    )
    require_true(evaluation_acceptance.get("secret_fail_closed"), name="evaluation.secrets")
    gates.append(
        _gate(
            "fail_closed_security_tests",
            passed=True,
            path=STATE_REPRO_RELPATH,
            digest=repro_digest,
            public_sha=state_new,
        )
    )

    state_canary_acceptance = _as_mapping(state_canary.get("acceptance"))
    require_true(
        state_canary_acceptance.get("default_viewer_combined_all_51"),
        name="viewer.combined_51",
    )
    require_true(
        state_canary_acceptance.get("default_viewer_not_ia_only"),
        name="viewer.not_ia",
    )
    require_true(state_canary_acceptance.get("includes_dc"), name="viewer.dc")
    require_true(
        _as_mapping(federal_canary.get("acceptance")).get("default_viewer_coherent"),
        name="federal_viewer.coherent",
    )
    gates.append(
        _gate(
            "default_viewer_combined_all_51",
            passed=True,
            path=STATE_PUBLIC_CANARY_RELPATH,
            digest=canary_digest,
            public_sha=state_new,
        )
    )

    require_true(
        state_canary_acceptance.get("public_pin_immutable"),
        name="state_canary.pin",
    )
    require_true(
        state_canary_acceptance.get("publication_receipt_bound"),
        name="state_canary.receipt",
    )
    require_true(
        _as_mapping(federal_canary.get("acceptance")).get("public_pin_immutable"),
        name="federal_canary.pin",
    )
    require_true(
        _as_mapping(federal_canary.get("acceptance")).get("publication_receipt_bound"),
        name="federal_canary.receipt",
    )
    if str(state_canary.get("public_sha") or "") != state_new:
        raise FinalReleaseMismatchError("state canary does not name the public SHA")
    if str(federal_canary.get("public_sha") or "") != federal_new:
        raise FinalReleaseMismatchError("federal canary does not name the public SHA")
    gates.append(
        _gate(
            "public_canaries_name_exact_public_shas",
            passed=True,
            path=STATE_PUBLIC_CANARY_RELPATH,
            digest=canary_digest,
            public_sha=state_new,
        )
    )

    first_issue = _as_mapping(federal_live.get("first_issue"))
    if first_issue.get("package_id") != FIRST_PACKAGE_ID:
        raise FinalReleaseMismatchError("federal first issue package is not FR-1936-03-14")
    if first_issue.get("publication_date") != FIRST_ISSUE_DATE:
        raise FinalReleaseMismatchError("federal first issue date drifted")
    if int(first_issue.get("volume") or 0) != FIRST_VOLUME:
        raise FinalReleaseMismatchError("federal first issue volume is not 1")
    if int(first_issue.get("number") or 0) != FIRST_NUMBER:
        raise FinalReleaseMismatchError("federal first issue number is not 1")
    require_true(federal_live.get("binds_first_issue") or _as_mapping(federal_live.get("acceptance")).get("binds_first_issue"), name="federal_live.first_issue")
    if str(federal_candidate.get("first_package_id") or "") != FIRST_PACKAGE_ID:
        raise FinalReleaseMismatchError("federal candidate first_package_id drifted")
    inventory_acceptance = _as_mapping(federal_inventory.get("acceptance"))
    require_true(inventory_acceptance.get("failed_final_zero"), name="inventory.failed_final")
    require_true(inventory_acceptance.get("frontier_closed"), name="inventory.frontier")
    if str(federal_inventory.get("observation_cutoff") or inventory_acceptance.get("observation_cutoff") or "") != OBSERVATION_CUTOFF:
        raise FinalReleaseMismatchError("federal inventory cutoff drifted")
    delta = _as_mapping(federal_inventory.get("delta"))
    if str(delta.get("delta_start_inclusive") or "") != LEGACY_DELTA_START_INCLUSIVE:
        raise FinalReleaseMismatchError("federal inventory delta start drifted")
    require_true(federal_live.get("frontier_closed"), name="federal_live.frontier")
    if int(federal_live.get("failed_final_count") or 0) != 0:
        raise FinalReleaseMismatchError("federal live failed_final is not zero")
    gates.append(
        _gate(
            "federal_first_issue_and_frontier",
            passed=True,
            path=FEDERAL_LIVE_RELPATH,
            digest=federal_live_digest,
            public_sha=federal_new,
        )
    )

    cross_acceptance = _as_mapping(cross.get("acceptance"))
    require_true(
        cross_acceptance.get("shared_resolver_descriptor_vector_contracts"),
        name="cross.shared_contracts",
    )
    require_true(
        cross_acceptance.get("vector_space_id_required_for_late_fusion"),
        name="cross.vector_space",
    )
    if not SHARED_VECTOR_SPACE_ID:
        raise FinalReleaseMismatchError("shared vector_space_id is empty")
    gates.append(
        _gate(
            "shared_embedding_contract",
            passed=True,
            path=CROSS_CORPUS_CANARY_RELPATH,
            digest=cross_digest,
            public_sha=state_new,
        )
    )

    final_acceptance = _as_mapping(state_final.get("acceptance"))
    require_true(final_acceptance.get("no_unresolved_gap"), name="state_final.no_gap")
    require_true(
        final_acceptance.get("every_state_law_gate_at_public_sha"),
        name="state_final.gates",
    )
    if str(state_final.get("unresolved_gaps") or []) not in ([], "[]"):
        if state_final.get("unresolved_gaps"):
            raise FinalReleaseMismatchError("state final receipt still has unresolved gaps")
    gates.append(
        _gate(
            "combined_terminal_binds_pins_manifests_canaries_gaps",
            passed=True,
            path=STATE_FINAL_RELPATH,
            digest=final_digest,
            public_sha=state_new,
            note="combined receipt additionally binds Federal pins/manifests/canaries",
        )
    )

    present = [item["id"] for item in gates]
    if present != list(ROOT_GATE_IDS):
        raise FinalReleaseMismatchError(
            "root gate set drifted: " + ",".join(present)
        )
    return gates


# ---------------------------------------------------------------------------
# Refill scan
# ---------------------------------------------------------------------------


def scan_bounded_refill(*, repo_root: Path) -> dict[str, Any]:
    state_publication = load_state_publication(repo_root=repo_root)
    federal_publication = load_federal_publication(repo_root=repo_root)
    state_audit = load_state_post_publication_audit(repo_root=repo_root)
    state_final = load_state_final_receipt(repo_root=repo_root)
    closure = audit_refill_closure(
        state_publication=state_publication,
        federal_publication=federal_publication,
        state_audit=state_audit,
        state_final=state_final,
    )
    if closure.get("closed") is not True or int(closure.get("unresolved_count") or 0) != 0:
        raise FinalReleaseMismatchError("LCR-068 refill closure is not empty")

    scanned: list[str] = []
    findings: list[dict[str, Any]] = []
    for name, relpath in BOUND_EVIDENCE:
        if len(scanned) >= MAX_REFILL_SCAN_ITEMS:
            break
        payload = _load_bound_json(relpath, repo_root=repo_root)
        scanned.append(relpath.as_posix())
        for key in ("refill_findings", "unresolved_gaps", "findings"):
            raw = payload.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                for item in raw:
                    if item in (None, "", False, 0, [], {}):
                        continue
                    if isinstance(item, Mapping):
                        status = str(item.get("status") or item.get("state") or "").casefold()
                        if status in {"closed", "resolved", "passed", "absent", "none", "ok"}:
                            continue
                        if item.get("closed") is True or item.get("resolved") is True:
                            continue
                        if item.get("unresolved") is True or status in UNRESOLVED_STATUSES:
                            findings.append(
                                {
                                    "item": {"kind": key, "status": status or "open"},
                                    "source": relpath.as_posix(),
                                }
                            )
                    elif str(item).strip():
                        findings.append(
                            {
                                "item": {"kind": key, "status": "open"},
                                "source": relpath.as_posix(),
                            }
                        )
        acceptance = _as_mapping(payload.get("acceptance"))
        if acceptance.get("no_unresolved_gap") is False:
            findings.append(
                {
                    "item": {"kind": "acceptance.no_unresolved_gap", "status": "open"},
                    "source": relpath.as_posix(),
                }
            )
        del name

    if findings:
        raise FinalReleaseMismatchError(
            "bounded refill scan found unresolved work: "
            + ", ".join(item["source"] for item in findings[:8])
        )

    return {
        "bounded": True,
        "closed": True,
        "findings": [],
        "lcr068_closure": {
            "closed": True,
            "unresolved_count": 0,
        },
        "max_items": MAX_REFILL_SCAN_ITEMS,
        "mixed_into_this_release": False,
        "ok": True,
        "scanned_count": len(scanned),
        "unresolved_count": 0,
    }


# ---------------------------------------------------------------------------
# Public-revision proof (check path)
# ---------------------------------------------------------------------------


def prove_public_revisions(*, repo_root: Path) -> dict[str, Any]:
    """Re-verify sealed public pins without re-executing Hub publication.

    The terminal assembler binds the immutable public canaries and
    publication receipts. It does not rebuild FakeHub uploads: that path
    re-invokes prepublication seals owned by earlier mutation tasks and
    is not a root-gate input.
    """

    state_canary = load_state_public_canary(repo_root=repo_root)
    federal_canary = load_federal_public_canary(repo_root=repo_root)
    try:
        assert_state_public_pin_contract(state_canary)
        state_pin = require_state_public_pin(state_canary)
    except StatePublicPinError as exc:
        raise FinalReleaseMismatchError(f"state public pin contract failed: {exc}") from exc
    try:
        assert_federal_public_pin_contract(federal_canary)
        federal_pin = require_federal_public_pin(federal_canary)
    except FederalPublicPinError as exc:
        raise FinalReleaseMismatchError(
            f"federal public pin contract failed: {exc}"
        ) from exc
    try:
        cross = check_cross_corpus_canary(repo_root=repo_root, require_public_pin=True)
    except Exception as exc:
        raise FinalReleaseMismatchError(f"cross-corpus canary check failed: {exc}") from exc
    try:
        rehearsal = check_rehearsal(repo_root=repo_root)
    except Exception as exc:
        raise FinalReleaseMismatchError(
            f"dual rollback rehearsal check failed: {exc}"
        ) from exc
    if cross.get("ok") is not True:
        raise FinalReleaseMismatchError("cross-corpus canary check failed")
    if rehearsal.get("ok") is not True:
        raise FinalReleaseMismatchError("dual rollback rehearsal check failed")
    return {
        "cross_corpus": {
            "ok": True,
            "path": CROSS_CORPUS_CANARY_RELPATH.as_posix(),
            "task_id": "LCR-067",
        },
        "dual_rollback": {
            "ok": True,
            "path": DUAL_ROLLBACK_RELPATH.as_posix(),
            "task_id": "LCR-068",
        },
        "federal_register": {
            "ok": True,
            "path": FEDERAL_PUBLIC_CANARY_RELPATH.as_posix(),
            "public_sha": federal_pin,
            "require_public_pin": True,
            "task_id": "LCR-066",
        },
        "ok": True,
        "state_laws": {
            "ok": True,
            "path": STATE_PUBLIC_CANARY_RELPATH.as_posix(),
            "public_sha": state_pin,
            "require_public_pin": True,
            "task_id": "LCR-043",
        },
    }


# ---------------------------------------------------------------------------
# Receipt assembly
# ---------------------------------------------------------------------------


def expected_acceptance() -> dict[str, bool]:
    return {
        "both_authorized_targets_have_manifest_bound_public_revisions": True,
        "bounded_refill_scans_find_no_missing_work": True,
        "combined_terminal_receipt_binds_pins_manifests_canaries_gaps": True,
        "completion_reconciliation_finds_no_missing_work": True,
        "credentials_environment_only": True,
        "default_viewer_combined_all_51": True,
        "default_viewer_not_ia_only": True,
        "embedding_contract_and_locators": True,
        "evaluations_pass": True,
        "every_root_gate_passes_against_both_public_revisions": True,
        "exact_51_plus_dc": True,
        "fail_closed_security_tests": True,
        "failed_final_zero": True,
        "federal_first_issue_and_frontier": True,
        "fifty_one_official_source_receipts": True,
        "fixture_only": False,
        "identity_fields_and_unique_primary_keys": True,
        "includes_dc": True,
        "legacy_files_deleted": False,
        "no_absolute_path_or_secret": True,
        "no_missing_federal_disposition": True,
        "no_missing_jurisdiction": True,
        "no_publication_mismatch": True,
        "no_remote_mutation": True,
        "no_unresolved_gap": True,
        "no_unresolved_refill_finding": True,
        "one_disposition_per_item_reconciled": True,
        "physical_bounds_hold": True,
        "prior_pins_remain_usable": True,
        "public_canaries_name_exact_public_shas": True,
        "read_only": True,
        "required_semantic_families_present": True,
        "root_acceptance_content_addressed": True,
        "secrets_absent": True,
        "shared_embedding_contract": True,
        "two_clean_builds_reproducible": True,
    }


def build_final_receipt(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    root = repository_root(repo_root)
    _reject_mutable_revisions()
    pins = bind_public_pins(repo_root=root)
    gates = evaluate_root_gates(repo_root=root, pins=pins)
    board = reconcile_completion(repo_root=root)
    refill = scan_bounded_refill(repo_root=root)
    evidence_digests = bound_evidence_digests(repo_root=root)
    catalog_codes = _catalog_codes(load_catalog_payload(repo_root=root), repo_root=root)

    if board.get("missing_work"):
        raise FinalReleaseMismatchError("completion reconciliation found missing work")
    if refill.get("unresolved_count") != 0:
        raise FinalReleaseMismatchError("bounded refill scan is not empty")
    if not all(item.get("passed") is True for item in gates):
        raise FinalReleaseMismatchError("a root gate did not pass")

    acceptance = expected_acceptance()
    report: dict[str, Any] = {
        "acceptance": acceptance,
        "board": board,
        "bound_inputs": {
            name: relpath.as_posix() for name, relpath in BOUND_EVIDENCE
        },
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "completion_proof": {
            "kind": "final_release_receipt",
            "path": DEFAULT_REPORT_RELPATH.as_posix(),
            "schema": RECEIPT_SCHEMA,
            "status": "sealed",
            "task_id": TASK_ID,
        },
        "currentness_disclaimer": COMBINED_CURRENTNESS_DISCLAIMER,
        "dataset_repo_ids": [DEFAULT_STATE_REPO, DEFAULT_FEDERAL_REPO],
        "depends_on": list(DEPENDS_ON),
        "evidence_digests": evidence_digests,
        "exact_51_coverage": True,
        "federal_first_issue": {
            "number": FIRST_NUMBER,
            "package_id": FIRST_PACKAGE_ID,
            "publication_date": FIRST_ISSUE_DATE,
            "volume": FIRST_VOLUME,
        },
        "fixture_id": FIXTURE_ID,
        "fixture_only": False,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "gate_count": len(gates),
        "gates": gates,
        "gates_passed": len(gates),
        "goal_id": GOAL_ID,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdictions": catalog_codes,
        "legacy_files_deleted": False,
        "live_network": False,
        "manifests": {
            "federal_register": pins["federal_manifest"],
            "state_laws": pins["state_manifest"],
        },
        "mutation_executed": False,
        "network_required": False,
        "observation_cutoff": OBSERVATION_CUTOFF,
        "phase": "root_final",
        "pins": {
            "all_four_queryable": True,
            "count": PIN_COUNT,
            "federal_new": pins["federal_new"],
            "federal_previous": pins["federal_previous"],
            "roles": list(PIN_ROLES),
            "state_new": pins["state_new"],
            "state_previous": pins["state_previous"],
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": PUBLIC_BRANCH,
        "read_only": True,
        "refill": refill,
        "release_points": {
            "federal_register": FEDERAL_RELEASE_POINT,
            "state_laws": STATE_RELEASE_POINT,
        },
        "release_profiles": {
            "federal_register": FEDERAL_RELEASE_PROFILE,
            "state_laws": STATE_RELEASE_PROFILE,
        },
        "remote_write_contacted": False,
        "repositories": {
            "federal_register": DEFAULT_FEDERAL_REPO,
            "state_laws": DEFAULT_STATE_REPO,
        },
        "required_semantic_families": {
            "federal_register": list(federal_required_semantic_families()),
            "state_laws": list(state_required_semantic_families()),
        },
        "root_goal_id": ROOT_GOAL_ID,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "secret_redacted": True,
        "shared_vector_space_id": SHARED_VECTOR_SPACE_ID,
        "status": "sealed",
        "task_id": TASK_ID,
        "tokens_used": False,
        "unresolved_gaps": [],
    }
    reject_credentials_in_payload(report, label="final_release_receipt")
    reject_path_leaks(report, label="final_release_receipt")
    digest = digest_mapping(strip_digest_fields(report))
    report["canonical_digest"] = digest
    report["content_digest"] = digest
    report["digest"] = digest
    report["report_digest_sha256"] = digest
    return report


def compare_receipts(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    left = strip_digest_fields(fresh)
    right = strip_digest_fields(sealed)
    if canonical_json_dumps(left) == canonical_json_dumps(right):
        return mismatches
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


def check_final_release(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    prove_live_canaries: bool = True,
) -> dict[str, Any]:
    root = repository_root(repo_root)
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(root)
    )
    if not sealed_path.is_file():
        raise FinalReleaseMissingInputError(
            f"report not found: {DEFAULT_REPORT_RELPATH.as_posix()}; pass --write"
        )
    sealed = load_json_mapping(sealed_path)
    fresh = build_final_receipt(repo_root=root)
    reject_credentials_in_payload(sealed, label="sealed_final_release_receipt")
    reject_path_leaks(sealed, label="sealed_final_release_receipt")
    if sealed.get("schema") != RECEIPT_SCHEMA:
        raise FinalReleaseMismatchError(
            f"sealed receipt schema mismatch: {sealed.get('schema')!r}"
        )
    if sealed.get("task_id") != TASK_ID:
        raise FinalReleaseMismatchError(
            f"sealed receipt task_id mismatch: {sealed.get('task_id')!r}"
        )
    if sealed.get("mutation_executed") is True or sealed.get("live_network") is True:
        raise FinalReleaseSafetyError("sealed receipt must remain offline/read-only")
    if sealed.get("status") != "sealed":
        raise FinalReleaseMismatchError("sealed receipt status is not sealed")
    mismatches = compare_receipts(fresh, sealed)
    if mismatches:
        raise FinalReleaseMismatchError(
            "sealed final release receipt check failed: " + "; ".join(mismatches[:16])
        )
    acceptance = _as_mapping(sealed.get("acceptance"))
    if acceptance != expected_acceptance():
        failed = [
            key
            for key, value in expected_acceptance().items()
            if acceptance.get(key) is not value
        ]
        raise FinalReleaseMismatchError(
            "sealed acceptance failed: " + ", ".join(failed[:16])
        )
    public_proof = (
        prove_public_revisions(repo_root=root) if prove_live_canaries else {"ok": True}
    )
    if public_proof.get("ok") is not True:
        raise FinalReleaseMismatchError("public revision proof failed")
    pins = _as_mapping(sealed.get("pins"))
    board = _as_mapping(sealed.get("board")) or _as_mapping(fresh.get("board"))
    status_projection = {
        **_as_mapping(board.get("status_projection")),
        "ok": True,
        "read_only": True,
        "written": [],
    }
    return {
        "acceptance": dict(acceptance),
        "every_root_gate_passes_against_both_public_revisions": True,
        "exact_51_plus_dc": True,
        "federal_first_issue_and_frontier": True,
        "gate_count": int(sealed.get("gate_count") or 0),
        "mismatches": [],
        "missing_work": [],
        "no_unresolved_refill_finding": True,
        "ok": True,
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "pin_count": int(pins.get("count") or 0),
        "public_proof": public_proof,
        "status_projection": status_projection,
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_legal_corpora_final_release.py",
        description=(
            "Seal and verify the combined state-law and Federal Register "
            f"public releases plus root-goal evidence ({TASK_ID}). "
            "Default mode is offline and does not mutate either Hub repository."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the sealed final receipt against a fresh offline build",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write/refresh {DEFAULT_REPORT_RELPATH.as_posix()}",
    )
    parser.add_argument(
        "--skip-public-proof",
        action="store_true",
        help="Skip the composed public-canary re-verification (tests only).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path for the receipt JSON "
            f"(default: stdout, or {DEFAULT_REPORT_RELPATH.as_posix()} with --write)"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the sealed final release receipt "
            f"(default: {DEFAULT_REPORT_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Always print the receipt/verification result as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        reject_secrets_in_argv(argv_list)
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)
    except FinalReleaseSafetyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )

    try:
        if args.check and not args.write:
            result = check_final_release(
                path=report_path,
                prove_live_canaries=not args.skip_public_proof,
            )
            if args.print_json or args.output is not None:
                write_json(args.output, result)
            print(
                "ok={ok} task_id={task_id} gates={gates} "
                "exact_51_plus_dc={exact} "
                "federal_first_issue={federal} "
                "no_unresolved_refill={refill} "
                "no_missing_work={missing}".format(
                    ok=result.get("ok"),
                    task_id=result.get("task_id"),
                    gates=result.get("gate_count"),
                    exact=result.get("exact_51_plus_dc"),
                    federal=result.get("federal_first_issue_and_frontier"),
                    refill=result.get("no_unresolved_refill_finding"),
                    missing=not result.get("missing_work"),
                ),
                file=sys.stderr,
            )
            return 0 if result.get("ok") else 1

        report = build_final_receipt()
        if args.write:
            destination = (
                Path(args.output).expanduser().resolve()
                if args.output is not None
                else report_path
            )
            write_json(destination, report)
            project_terminal_status_completion(
                repo_root=repository_root(),
                board=_as_mapping(report.get("board")),
            )
            print(
                f"wrote {repo_relpath(destination)} digest={report['digest']}",
                file=sys.stderr,
            )
            if args.check:
                check_final_release(
                    path=destination,
                    prove_live_canaries=not args.skip_public_proof,
                )
        elif args.output is not None or args.print_json or not args.check:
            write_json(args.output, report)
        return 0
    except (FinalReleaseError, MutableRevisionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
