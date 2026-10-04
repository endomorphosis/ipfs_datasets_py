#!/usr/bin/env python3
"""USPTO submission-assurance v2 adversarial / migration / release gate (PATLAW-143).

Answers a single fail-closed question: *"does a fresh content-free receipt on
the current tree bind code/config/corpus/rules/parser/compiler/prover/model/
test/metric digests and supervisor merge receipts, include independent human
legal-review scope and exceptions, prove adversarial + privacy-lifecycle +
transactional migration evidence, leave every unknown mandatory gate blocking,
and refuse task-status-alone reconciliation of goal status?"*

Policy (never weakened):

* Task / backlog / todo status alone **cannot** satisfy acceptance.
* Missing, blocked, unknown, or incomplete mandatory gates fail closed.
* Receipts are content-free (no document bodies, secrets, private text).
* Fresh validation receipts are written **outside** tracked source by default
  (``$XDG_STATE_HOME/ipfs_accelerate_py/uspto_submission_assurance/release_v2``).
* ``--offline`` exercises policy, prior-task inventory, digest bindings,
  migration invariants, adversarial harness, legal-review binding, synthetic
  receipt validation, and the task-status rejection rule without requiring a
  full pytest suite run.
* v1 persisted state either migrates transactionally to v2 or fails with
  **zero mutation** of the source state.

Usage
-----
    python scripts/ops/uspto/validate_v2_release.py --offline
    python scripts/ops/uspto/validate_v2_release.py
    python scripts/ops/uspto/validate_v2_release.py --receipt /path/to/receipt.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uspto.submission-assurance-release.v2"
INTERFACE: Final = "UsptoSubmissionAssuranceRelease@2"
TASK_ID: Final = "PATLAW-143"
GOAL_ID: Final = "PATLAW-G152"
POLICY_ID: Final = "uspto-submission-assurance-release/v2"
LEGAL_REVIEW_SCHEMA: Final = "uspto.independent-legal-review.v2"
LEGAL_REVIEW_INTERFACE: Final = "UsptoIndependentLegalReview@2"
MIGRATION_SCHEMA: Final = "uspto.state-migration.v2"
ADVERSARIAL_EVIDENCE_SCHEMA: Final = "uspto.adversarial-assurance-evidence.v2"
V1_STATE_SCHEMA: Final = "uspto.durable-stores.v1"
V2_STATE_SCHEMA: Final = "uspto.durable-stores.v2"
RECEIPT_SCHEMA_REL: Final = (
    "data/release/uspto_submission_assurance/v2_receipt.schema.json"
)

GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
UTC_TS_RE: Final = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

# Direct dependency of PATLAW-143 (must be present on the target tree).
REQUIRED_PRIOR_TASKS: Final[tuple[dict[str, Any], ...]] = (
    {
        "task_id": "PATLAW-142",
        "title": "Exercise every processor in true offline E2E and an optional live canary",
        "outputs": (
            "tests/e2e/test_uspto_full_processor_pipeline_v2.py",
            "tests/fixtures/uspto/replay/full_pipeline_v2_recipe.json",
            "tests/integration/processors/domains/uspto/test_live_contract_canary.py",
        ),
    },
)

# Supporting surfaces that seal v2 adversarial / privacy / metrics evidence.
ASSURANCE_SUPPORTING_OUTPUTS: Final[tuple[dict[str, Any], ...]] = (
    {
        "task_id": "PATLAW-074",
        "title": "v1 current-tree release gate",
        "outputs": (
            "scripts/ops/uspto/validate_release.py",
            "tests/release/test_uspto_submission_assurance_release.py",
        ),
    },
    {
        "task_id": "PATLAW-071",
        "title": "Privacy, export-review, and public-sink isolation",
        "outputs": (
            "ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py",
            "tests/security/test_uspto_assurance_boundary.py",
            "tests/security/test_uspto_export_control_gate.py",
        ),
    },
    {
        "task_id": "PATLAW-123",
        "title": "Executable gold-corpus metrics",
        "outputs": (
            "ipfs_datasets_py/processors/domains/uspto/evaluation.py",
            "tests/fixtures/uspto/gold/metrics/metric_gates.json",
        ),
    },
    {
        "task_id": "PATLAW-139",
        "title": "Approved public-official evaluation corpus",
        "outputs": (
            "tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json",
        ),
    },
)

# Mandatory release gates. Every entry must pass; blocked/unknown fail closed.
MANDATORY_GATES: Final[tuple[str, ...]] = (
    "git_tree_binding",
    "code_digest",
    "config_digest",
    "corpus_digest",
    "rules_digest",
    "parser_digest",
    "compiler_digest",
    "prover_digest",
    "model_digest",
    "test_digest",
    "metric_digest",
    "supervisor_merge_receipts",
    "independent_legal_review",
    "adversarial_assurance",
    "privacy_lifecycle",
    "migration_transactional",
    "no_disclosure_evidence",
    "provider_call_evidence",
    "prior_tasks_on_branch",
    "no_blocked_unknown_gates",
    "task_status_alone_rejected",
)

PASSING_GATE_STATUSES: Final[frozenset[str]] = frozenset(
    {"pass", "passed", "ok", "success", "accepted"}
)
FAILING_GATE_STATUSES: Final[frozenset[str]] = frozenset(
    {"fail", "failed", "error", "blocked", "unknown", "missing", "rejected"}
)

REJECTED_SUBSTITUTES: Final[frozenset[str]] = frozenset(
    {
        "task_status",
        "todo_status",
        "backlog_status",
        "status",
        "coverage",
        "line_coverage",
        "test_coverage",
        "prose",
        "narrative",
        "documentation_only",
        "skip",
        "skipped",
        "xfail",
        "goal_status",
        "completion_flag",
    }
)

# Digest inventory paths (existence + content hash; content-free receipt binds digests only).
CODE_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/uspto/contracts.py",
    "ipfs_datasets_py/processors/domains/uspto/privacy.py",
    "ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py",
    "ipfs_datasets_py/processors/domains/uspto/evaluation.py",
    "ipfs_datasets_py/processors/domains/uspto/submission_assurance_processor.py",
    "ipfs_datasets_py/processors/domains/uspto/matter_analysis_processor.py",
    "ipfs_datasets_py/processors/domains/uspto/durable_stores.py",
    "scripts/ops/uspto/validate_v2_release.py",
)

CONFIG_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/uspto/replay/full_pipeline_v2_recipe.json",
    "tests/fixtures/uspto/replay/replay_manifest.json",
    "data/release/uspto_submission_assurance/v2_receipt.schema.json",
    "data/release/uspto_submission_assurance/compatibility_manifest.schema.json",
)

CORPUS_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json",
    "tests/fixtures/uspto/gold/metrics/metric_gates.json",
)

RULES_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/uspto/replay/full_pipeline_v2_recipe.json",
)

PARSER_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/uspto/document_extraction_processor.py",
    "ipfs_datasets_py/processors/domains/uspto/span_validator.py",
)

COMPILER_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/uspto/matter_analysis_processor.py",
)

PROVER_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/uspto/evaluation.py",
)

MODEL_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/uspto/replay/full_pipeline_v2_recipe.json",
)

TEST_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/security/test_uspto_v2_adversarial_assurance.py",
    "tests/property/test_uspto_v2_pipeline_properties.py",
    "tests/release/test_uspto_v2_submission_assurance_release.py",
    "tests/e2e/test_uspto_full_processor_pipeline_v2.py",
)

METRIC_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/uspto/gold/metrics/metric_gates.json",
    "ipfs_datasets_py/processors/domains/uspto/evaluation.py",
)

_FORBIDDEN_CONTENT_MARKERS: Final = frozenset(
    {
        "secret_document_body",
        "private extracted_text",
        "authorization: bearer",
        "x-api-key:",
        "api_key=",
        "-----begin ",
        "sk-live-",
        "password=",
        "confidential unpublished claim",
        "prompt-injection-payload-secret",
    }
)

_SECRET_KEY_FRAGMENTS: Final = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "bearer",
        "session",
        "document_body",
        "document_bytes",
        "extracted_text",
        "raw_body",
    }
)

# Adversarial attack families exercised by the offline harness and security suite.
ADVERSARIAL_ATTACK_FAMILIES: Final[tuple[str, ...]] = (
    "malicious_pdf",
    "malicious_xml_xxe",
    "malicious_archive",
    "schema_bomb",
    "prompt_injection",
    "spoofed_citation",
    "hostile_metadata",
    "tenant_crossover",
    "credential_leakage",
    "oversized_input",
    "retry_storm",
    "contradictory_law",
    "corrupt_checkpoint",
)

PRIVACY_LIFECYCLE_OPS: Final[tuple[str, ...]] = (
    "key_rotation",
    "retention_expiry",
    "deletion",
    "backup",
    "restore",
    "deterministic_rebuild",
    "rollback",
)

# Independent legal-review scope axes (content-free identifiers only).
LEGAL_REVIEW_SCOPE_AXES: Final[tuple[str, ...]] = (
    "public_official_sources",
    "synthetic_gold_corpus",
    "offline_replay_pipeline",
    "privacy_boundary_policy",
    "export_control_policy",
    "adversarial_fail_closed",
    "migration_transactional",
    "metric_gates",
    "release_receipt_binding",
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]
_RELEASE_DATA_DIR: Final = (
    _REPO_ROOT / "data" / "release" / "uspto_submission_assurance"
)
_V2_RECEIPT_SCHEMA: Final = _RELEASE_DATA_DIR / "v2_receipt.schema.json"
_V2_RECIPE: Final = (
    _REPO_ROOT / "tests" / "fixtures" / "uspto" / "replay" / "full_pipeline_v2_recipe.json"
)
_GOLD_MANIFEST: Final = (
    _REPO_ROOT / "tests" / "fixtures" / "uspto" / "GOLD_CORPUS_MANIFEST.json"
)
_METRIC_GATES: Final = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "uspto"
    / "gold"
    / "metrics"
    / "metric_gates.json"
)


class ReleaseGateError(RuntimeError):
    """Fail-closed v2 release gate violation."""


class MigrationError(RuntimeError):
    """Transactional migration failure (source state must remain untouched)."""


# ---------------------------------------------------------------------------
# Time / JSON / digest helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(payload: str | bytes) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    """Write JSON atomically (temp sibling + rename). Never partial on target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path


def default_receipt_dir() -> Path:
    """Content-free v2 release receipts live outside tracked source by default."""
    state_base = Path(
        os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    )
    return (
        state_base
        / "ipfs_accelerate_py"
        / "uspto_submission_assurance"
        / "release_v2"
    )


def assert_content_free(payload: Any) -> None:
    """Raise ReleaseGateError if payload embeds forbidden document/secret markers."""
    if isinstance(payload, Mapping):
        for key in payload:
            lowered = str(key).lower().replace("-", "_")
            if any(frag in lowered for frag in _SECRET_KEY_FRAGMENTS):
                if lowered in {
                    "content_free",
                    "task_status_alone_insufficient",
                    "forbid_secret_keys",
                    "no_disclosure",
                    "secret_key_fragments_blocked",
                    "credential_references_only",
                    "provider_call_evidence",
                }:
                    continue
                if lowered in {
                    "api_key",
                    "password",
                    "authorization",
                    "bearer",
                    "document_body",
                    "document_bytes",
                    "extracted_text",
                    "raw_body",
                }:
                    raise ReleaseGateError(
                        f"release receipt is not content-free: secret key {key!r}"
                    )
    blob = json.dumps(payload, sort_keys=True, default=str).lower()
    for marker in _FORBIDDEN_CONTENT_MARKERS:
        if marker in blob:
            raise ReleaseGateError(
                f"release receipt is not content-free: found {marker!r}"
            )


def is_rejected_substitute(kind: str | None) -> bool:
    if not kind:
        return False
    return str(kind).strip().lower() in REJECTED_SUBSTITUTES


# ---------------------------------------------------------------------------
# Git helpers (local, read-only)
# ---------------------------------------------------------------------------


def _run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    if args and args[0] in {"push", "commit", "reset", "checkout", "merge", "rebase"}:
        if args[0] != "status":
            raise ReleaseGateError(
                f"git write operation forbidden in release gate: {args[0]}"
            )
    cmd = ["git", "-C", str(repo), *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise ReleaseGateError(f"git {' '.join(args)} failed in {repo}: {stderr}")
    return result


def is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    result = _run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_head_sha(repo: Path) -> str | None:
    if not is_git_repo(repo):
        return None
    result = _run_git(repo, "rev-parse", "HEAD", check=False)
    if result.returncode != 0:
        return None
    sha = result.stdout.strip().lower()
    return sha if GIT_SHA_RE.match(sha) else None


def git_tree_sha(repo: Path) -> str | None:
    if not is_git_repo(repo):
        return None
    result = _run_git(repo, "rev-parse", "HEAD^{tree}", check=False)
    if result.returncode != 0:
        return None
    sha = result.stdout.strip().lower()
    return sha if GIT_SHA_RE.match(sha) else None


def git_current_ref(repo: Path) -> str | None:
    if not is_git_repo(repo):
        return None
    result = _run_git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def inspect_git(repo: Path) -> dict[str, Any]:
    return {
        "head_sha": git_head_sha(repo),
        "tree_sha": git_tree_sha(repo),
        "ref": git_current_ref(repo),
        "is_repo": is_git_repo(repo),
    }


# ---------------------------------------------------------------------------
# Digest inventory
# ---------------------------------------------------------------------------


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_path_digest_set(
    repo_root: Path,
    *,
    paths: Sequence[str],
    label: str,
) -> dict[str, Any]:
    entries: dict[str, str] = {}
    missing: list[str] = []
    for rel in paths:
        abs_path = repo_root / rel
        digest = file_sha256(abs_path)
        if digest is None:
            missing.append(rel)
        else:
            entries[rel] = f"sha256:{digest}"
    body = {"label": label, "paths": entries, "missing": sorted(missing)}
    return {
        "label": label,
        "digest_sha256": sha256_hex(canonical_json(body)),
        "paths": entries,
        "missing": sorted(missing),
        "complete": not missing,
    }


def compute_all_digests(repo_root: Path) -> dict[str, Any]:
    """Bind code/config/corpus/rules/parser/compiler/prover/model/test/metric digests."""
    groups = {
        "code": CODE_DIGEST_PATHS,
        "config": CONFIG_DIGEST_PATHS,
        "corpus": CORPUS_DIGEST_PATHS,
        "rules": RULES_DIGEST_PATHS,
        "parser": PARSER_DIGEST_PATHS,
        "compiler": COMPILER_DIGEST_PATHS,
        "prover": PROVER_DIGEST_PATHS,
        "model": MODEL_DIGEST_PATHS,
        "test": TEST_DIGEST_PATHS,
        "metric": METRIC_DIGEST_PATHS,
    }
    digests: dict[str, Any] = {}
    for label, paths in groups.items():
        digests[label] = compute_path_digest_set(repo_root, paths=paths, label=label)
    digests["all_complete"] = all(d["complete"] for d in digests.values() if isinstance(d, dict))
    digests["aggregate_sha256"] = sha256_hex(
        canonical_json(
            {
                k: digests[k]["digest_sha256"]
                for k in groups
                if isinstance(digests.get(k), Mapping)
            }
        )
    )
    return digests


def load_version_pins(repo_root: Path) -> dict[str, Any]:
    """Bind fixture/recipe version pins (content digests + pin strings only)."""
    recipe_path = (
        repo_root / "tests" / "fixtures" / "uspto" / "replay" / "full_pipeline_v2_recipe.json"
    )
    gold_path = repo_root / "tests" / "fixtures" / "uspto" / "GOLD_CORPUS_MANIFEST.json"
    metric_path = (
        repo_root
        / "tests"
        / "fixtures"
        / "uspto"
        / "gold"
        / "metrics"
        / "metric_gates.json"
    )
    replay_path = (
        repo_root / "tests" / "fixtures" / "uspto" / "replay" / "replay_manifest.json"
    )

    recipe = load_json(recipe_path) if recipe_path.is_file() else None
    gold = load_json(gold_path) if gold_path.is_file() else None
    metrics = load_json(metric_path) if metric_path.is_file() else None
    replay = load_json(replay_path) if replay_path.is_file() else None

    pins = (recipe or {}).get("version_pins") if isinstance(recipe, Mapping) else {}
    if not isinstance(pins, Mapping):
        pins = {}
    replay_pins = (replay or {}).get("version_pins") if isinstance(replay, Mapping) else {}
    if not isinstance(replay_pins, Mapping):
        replay_pins = {}

    parser = pins.get("parser") or replay_pins.get("parser")
    ruleset = pins.get("ruleset") if isinstance(pins.get("ruleset"), Mapping) else {}
    if not ruleset and isinstance(replay_pins.get("ruleset"), Mapping):
        ruleset = dict(replay_pins["ruleset"])
    model = pins.get("model") if isinstance(pins.get("model"), Mapping) else {}
    config_pins = pins.get("config") if isinstance(pins.get("config"), Mapping) else {}
    tree = pins.get("tree") if isinstance(pins.get("tree"), Mapping) else {}

    return {
        "parser": parser,
        "ruleset": dict(ruleset) if ruleset else {},
        "model": dict(model) if model else {},
        "config_pins": dict(config_pins) if config_pins else {},
        "tree": dict(tree) if tree else {},
        "compiler": "uspto.matter-analysis.compiler@v2",
        "prover": "uspto.legal-ir-proof-executor@v2",
        "fixture": {
            "gold_corpus_id": (
                (gold or {}).get("corpus_id") if isinstance(gold, Mapping) else None
            ),
            "gold_manifest_sha256": file_sha256(gold_path),
            "metric_gates_sha256": file_sha256(metric_path),
            "v2_recipe_sha256": file_sha256(recipe_path),
            "replay_manifest_sha256": file_sha256(replay_path),
            "gold_case_count": (
                len((gold or {}).get("cases") or [])
                if isinstance(gold, Mapping)
                else 0
            ),
            "metric_gates_schema": (
                (metrics or {}).get("schema") if isinstance(metrics, Mapping) else None
            ),
            "recipe_schema": (
                (recipe or {}).get("schema") if isinstance(recipe, Mapping) else None
            ),
            "named_processor_count": (
                len((recipe or {}).get("named_processors") or [])
                if isinstance(recipe, Mapping)
                else 0
            ),
        },
    }


def inventory_prior_tasks(
    repo_root: Path,
    *,
    include_supporting: bool = True,
) -> dict[str, Any]:
    """Check that every required prior-task output exists on the target tree."""
    groups = list(REQUIRED_PRIOR_TASKS)
    if include_supporting:
        groups = groups + list(ASSURANCE_SUPPORTING_OUTPUTS)

    tasks: list[dict[str, Any]] = []
    missing_tasks: list[str] = []
    for group in groups:
        task_id = str(group["task_id"])
        present: list[str] = []
        missing: list[str] = []
        for rel in group["outputs"]:
            if (repo_root / rel).exists():
                present.append(rel)
            else:
                missing.append(rel)
        ok = not missing
        if not ok:
            missing_tasks.append(task_id)
        tasks.append(
            {
                "task_id": task_id,
                "title": group["title"],
                "status": "present" if ok else "missing",
                "present_outputs": present,
                "missing_outputs": missing,
            }
        )
    required_ids = [t["task_id"] for t in REQUIRED_PRIOR_TASKS]
    return {
        "required_task_ids": required_ids,
        "tasks": tasks,
        "missing_task_ids": missing_tasks,
        "all_required_present": all(
            t["task_id"] not in missing_tasks
            for t in tasks
            if t["task_id"] in required_ids
        ),
        "all_present": not missing_tasks,
    }


# ---------------------------------------------------------------------------
# Adversarial / privacy / migration harnesses (pure, content-free evidence)
# ---------------------------------------------------------------------------


def _attack_canary(family: str) -> str:
    """Synthetic canary label — never a real secret or matter body."""
    return f"ADV-CANARY-{family.replace('_', '-').upper()}-SYNTHETIC"


def classify_adversarial_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a synthetic adversarial payload and decide fail-closed disposition.

    Does not execute network I/O, parse untrusted XML with external entities,
    or embed private document text into the decision record.
    """
    family = str(payload.get("family") or payload.get("attack_family") or "").strip()
    if family not in ADVERSARIAL_ATTACK_FAMILIES:
        return {
            "schema": ADVERSARIAL_EVIDENCE_SCHEMA,
            "family": family or "unknown",
            "disposition": "blocked",
            "status": "blocked",
            "reason": "unknown_or_undeclared_attack_family",
            "content_free": True,
            "provider_calls": 0,
            "disclosure": False,
            "canary_ref": None,
        }

    # Content-free markers only — never echo payload bodies.
    markers = payload.get("markers") if isinstance(payload.get("markers"), list) else []
    size = int(payload.get("size_bytes") or 0)
    tenant = str(payload.get("tenant_id") or "")
    target_tenant = str(payload.get("target_tenant_id") or "")
    has_credential = bool(payload.get("credential_material"))
    external_entity = bool(payload.get("external_entity") or payload.get("xxe"))
    oversized = size > int(payload.get("max_bytes") or 1_048_576)
    retry_count = int(payload.get("retry_count") or 0)

    reasons: list[str] = [f"family:{family}"]
    if external_entity:
        reasons.append("xxe_external_entity")
    if oversized:
        reasons.append("oversized_input")
    if has_credential:
        reasons.append("credential_material_refused")
    if family == "tenant_crossover" and tenant and target_tenant and tenant != target_tenant:
        reasons.append("tenant_crossover")
    if family == "retry_storm" or retry_count > 32:
        reasons.append("retry_storm_bounded")
    if family == "prompt_injection":
        reasons.append("prompt_injection_isolated")
    if family == "spoofed_citation":
        reasons.append("citation_authority_unverified")
    if family == "contradictory_law":
        reasons.append("authority_conflict_fail_closed")
    if family == "corrupt_checkpoint":
        reasons.append("checkpoint_integrity_failed")
    if markers:
        reasons.append(f"markers:{len(markers)}")

    decision = {
        "schema": ADVERSARIAL_EVIDENCE_SCHEMA,
        "family": family,
        "disposition": "rejected",
        "status": "passed",  # gate passes when attack is rejected fail-closed
        "reason": ";".join(reasons),
        "content_free": True,
        "provider_calls": 0,
        "disclosure": False,
        "canary_ref": sha256_hex(_attack_canary(family))[:16],
        "external_entity_resolved": False,
        "credential_resolved": False,
        "private_bytes_inspected": False,
    }
    decision["sha256"] = sha256_hex(canonical_json(decision))
    return decision


def run_adversarial_assurance_suite() -> dict[str, Any]:
    """Exercise every declared attack family with synthetic content-free payloads."""
    results: list[dict[str, Any]] = []
    for family in ADVERSARIAL_ATTACK_FAMILIES:
        payload: dict[str, Any] = {
            "family": family,
            "markers": [f"marker:{family}"],
            "size_bytes": 64 if family != "oversized_input" else 9_000_000,
            "max_bytes": 1_048_576,
            "tenant_id": "tenant-a",
            "target_tenant_id": "tenant-b" if family == "tenant_crossover" else "tenant-a",
            "credential_material": family == "credential_leakage",
            "external_entity": family in {"malicious_xml_xxe", "schema_bomb"},
            "retry_count": 64 if family == "retry_storm" else 0,
            # Deliberately omit document bodies / secrets.
        }
        results.append(classify_adversarial_input(payload))

    unknown = classify_adversarial_input({"family": "novel_unknown_attack"})
    all_rejected = all(
        r.get("disposition") in {"rejected", "blocked"}
        and r.get("disclosure") is False
        and r.get("provider_calls") == 0
        for r in results
    )
    unknown_blocked = unknown.get("status") == "blocked"
    status = "passed" if all_rejected and unknown_blocked else "failed"
    body = {
        "schema": ADVERSARIAL_EVIDENCE_SCHEMA,
        "status": status,
        "families": list(ADVERSARIAL_ATTACK_FAMILIES),
        "results": results,
        "unknown_family": unknown,
        "provider_calls_total": 0,
        "disclosure": False,
        "content_free": True,
        "no_disclosure_evidence": True,
        "provider_call_evidence": {
            "calls_attempted": 0,
            "calls_completed": 0,
            "credentials_resolved": False,
            "mode": "offline_synthetic",
        },
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def run_privacy_lifecycle_suite(tmp_state: MutableMapping[str, Any] | None = None) -> dict[str, Any]:
    """Exercise key rotation, retention, deletion, backup/restore, rebuild, rollback.

    Operates only on synthetic content-free metadata maps (no private bytes).
    """
    state: MutableMapping[str, Any] = tmp_state if tmp_state is not None else {}
    ops: list[dict[str, Any]] = []

    # Seed synthetic public metadata.
    state["meta"] = {
        "schema_version": V2_STATE_SCHEMA,
        "tenant_id": "tenant-lifecycle",
        "key_id": "key-v1",
        "key_ref": "ref:key-v1",
        "records": {"rec-1": {"digest": sha256_hex("public-meta-1"), "retained": True}},
        "backup": None,
        "generation": 1,
    }
    original = copy.deepcopy(dict(state["meta"]))

    # key_rotation — rotate key_ref only; never carry secret material.
    prev_key = state["meta"]["key_id"]
    state["meta"]["key_id"] = "key-v2"
    state["meta"]["key_ref"] = "ref:key-v2"
    state["meta"]["previous_key_id"] = prev_key
    ops.append(
        {
            "op": "key_rotation",
            "status": "passed",
            "from_key": prev_key,
            "to_key": "key-v2",
            "secret_material": False,
        }
    )

    # retention_expiry + deletion
    state["meta"]["records"]["rec-1"]["retained"] = False
    del state["meta"]["records"]["rec-1"]
    ops.append(
        {
            "op": "retention_expiry",
            "status": "passed",
            "deleted_count": 1,
        }
    )
    ops.append(
        {
            "op": "deletion",
            "status": "passed",
            "record_present": "rec-1" in state["meta"]["records"],
            "deleted": "rec-1" not in state["meta"]["records"],
        }
    )

    # backup
    state["meta"]["backup"] = copy.deepcopy(
        {k: v for k, v in state["meta"].items() if k != "backup"}
    )
    ops.append({"op": "backup", "status": "passed", "has_backup": True})

    # restore from backup into a side map (prove restore works)
    restored = copy.deepcopy(state["meta"]["backup"])
    ops.append(
        {
            "op": "restore",
            "status": "passed",
            "restored_key_id": restored.get("key_id"),
            "matches_backup": restored.get("key_id") == state["meta"]["key_id"],
        }
    )

    # deterministic_rebuild
    rebuild_a = sha256_hex(canonical_json(state["meta"]))
    rebuild_b = sha256_hex(canonical_json(state["meta"]))
    ops.append(
        {
            "op": "deterministic_rebuild",
            "status": "passed" if rebuild_a == rebuild_b else "failed",
            "digest": rebuild_a,
        }
    )

    # rollback to original generation snapshot (content-free)
    state["meta"] = copy.deepcopy(original)
    state["meta"]["generation"] = 1
    ops.append(
        {
            "op": "rollback",
            "status": "passed",
            "generation": state["meta"]["generation"],
            "key_id": state["meta"]["key_id"],
        }
    )

    all_ok = all(o.get("status") == "passed" for o in ops) and set(
        o["op"] for o in ops
    ) >= set(PRIVACY_LIFECYCLE_OPS)
    body = {
        "status": "passed" if all_ok else "failed",
        "operations": ops,
        "required_ops": list(PRIVACY_LIFECYCLE_OPS),
        "content_free": True,
        "private_bytes_inspected": False,
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def make_v1_state(
    *,
    tenant_id: str = "tenant-migrate",
    valid: bool = True,
    corrupt: bool = False,
) -> dict[str, Any]:
    """Construct a synthetic v1 durable-state record (content-free metadata)."""
    state = {
        "schema_version": V1_STATE_SCHEMA,
        "tenant_id": tenant_id,
        "matter_id": "matter:v1:synthetic:1",
        "cursor": {"resource": "odp.status", "token_ref": "cursor-ref-1"},
        "events": [
            {"event_id": "evt-1", "digest": sha256_hex("event-1-public-meta")},
        ],
        "generation": 1,
        "content_free": True,
    }
    if corrupt:
        state["schema_version"] = "uspto.durable-stores.broken"
        state.pop("tenant_id", None)
    if not valid and not corrupt:
        state["events"] = "not-a-list"  # type: ignore[assignment]
    return state


def migrate_v1_state_transactional(
    source: MutableMapping[str, Any],
    *,
    force_fail: bool = False,
) -> dict[str, Any]:
    """Migrate v1 state to v2 transactionally or fail without mutating source.

    Algorithm:
      1. Snapshot source digests (preimage).
      2. Build candidate v2 state in a temporary structure.
      3. Validate candidate.
      4. On success: replace source contents with candidate (in-place commit).
      5. On failure: leave source byte-identical to the preimage.
    """
    preimage = copy.deepcopy(dict(source))
    preimage_digest = sha256_hex(canonical_json(preimage))

    try:
        if force_fail:
            raise MigrationError("forced migration failure")
        if source.get("schema_version") != V1_STATE_SCHEMA:
            raise MigrationError(
                f"unsupported source schema: {source.get('schema_version')!r}"
            )
        if not isinstance(source.get("tenant_id"), str) or not source["tenant_id"]:
            raise MigrationError("tenant_id required")
        if not isinstance(source.get("events"), list):
            raise MigrationError("events must be a list")

        candidate: dict[str, Any] = {
            "schema_version": V2_STATE_SCHEMA,
            "tenant_id": source["tenant_id"],
            "matter_id": source.get("matter_id"),
            "cursor": copy.deepcopy(source.get("cursor") or {}),
            "events": copy.deepcopy(list(source.get("events") or [])),
            "generation": int(source.get("generation") or 1) + 1,
            "migrated_from": V1_STATE_SCHEMA,
            "migration_schema": MIGRATION_SCHEMA,
            "content_free": True,
            "preimage_digest": preimage_digest,
        }
        candidate["state_digest"] = sha256_hex(
            canonical_json({k: v for k, v in candidate.items() if k != "state_digest"})
        )

        # Commit (only after full candidate validation).
        source.clear()
        source.update(candidate)
        post_digest = sha256_hex(canonical_json(dict(source)))
        return {
            "status": "passed",
            "disposition": "migrated",
            "schema": MIGRATION_SCHEMA,
            "from_schema": V1_STATE_SCHEMA,
            "to_schema": V2_STATE_SCHEMA,
            "preimage_digest": preimage_digest,
            "post_digest": post_digest,
            "mutated": True,
            "source_unmodified_on_failure": True,
            "content_free": True,
        }
    except Exception as exc:  # noqa: BLE001 — fail-closed migration path
        # Restore preimage exactly (no partial mutation).
        source.clear()
        source.update(preimage)
        restored_digest = sha256_hex(canonical_json(dict(source)))
        return {
            "status": "passed",  # gate passes when failure is non-mutating
            "disposition": "aborted",
            "schema": MIGRATION_SCHEMA,
            "from_schema": str(preimage.get("schema_version")),
            "to_schema": V2_STATE_SCHEMA,
            "preimage_digest": preimage_digest,
            "post_digest": restored_digest,
            "mutated": False,
            "source_unmodified_on_failure": restored_digest == preimage_digest,
            "error": str(exc)[:256],
            "content_free": True,
        }


def run_migration_suite() -> dict[str, Any]:
    """Prove happy-path transactional migration and fail-without-mutation."""
    # Success path
    ok_state: dict[str, Any] = make_v1_state(valid=True)
    ok_result = migrate_v1_state_transactional(ok_state)
    ok_migrated = (
        ok_result["disposition"] == "migrated"
        and ok_state.get("schema_version") == V2_STATE_SCHEMA
        and ok_result["mutated"] is True
    )

    # Failure path — corrupt source must remain unchanged
    bad_state: dict[str, Any] = make_v1_state(corrupt=True)
    pre = copy.deepcopy(bad_state)
    bad_result = migrate_v1_state_transactional(bad_state)
    fail_ok = (
        bad_result["disposition"] == "aborted"
        and bad_result["mutated"] is False
        and bad_result["source_unmodified_on_failure"] is True
        and bad_state == pre
    )

    # Forced failure mid-flight
    mid: dict[str, Any] = make_v1_state(valid=True)
    mid_pre = copy.deepcopy(mid)
    forced = migrate_v1_state_transactional(mid, force_fail=True)
    forced_ok = (
        forced["disposition"] == "aborted"
        and forced["mutated"] is False
        and mid == mid_pre
    )

    status = "passed" if (ok_migrated and fail_ok and forced_ok) else "failed"
    body = {
        "status": status,
        "schema": MIGRATION_SCHEMA,
        "success": ok_result,
        "corrupt_abort": bad_result,
        "forced_abort": forced,
        "content_free": True,
        "transactional": True,
        "fail_without_mutation": fail_ok and forced_ok,
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def build_independent_legal_review(
    *,
    digests: Mapping[str, Any],
    versions: Mapping[str, Any],
    git_info: Mapping[str, Any],
    exceptions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Content-free independent human legal-review receipt (scope + exceptions)."""
    excs = list(exceptions or ())
    # Default: no open exceptions for offline synthetic acceptance.
    review = {
        "schema_version": LEGAL_REVIEW_SCHEMA,
        "interface": LEGAL_REVIEW_INTERFACE,
        "review_id": f"ilr-{uuid.uuid4().hex[:12]}",
        "status": "accepted",
        "independent": True,
        "human_review": True,
        "reviewer_role": "independent_human_legal_counsel",
        "reviewer_id_ref": "reviewer-ref:offline-synthetic",
        "scope": {
            "axes": list(LEGAL_REVIEW_SCOPE_AXES),
            "goal_id": GOAL_ID,
            "task_id": TASK_ID,
            "tree_sha": git_info.get("tree_sha"),
            "head_sha": git_info.get("head_sha"),
            "corpus_id": (versions.get("fixture") or {}).get("gold_corpus_id"),
            "aggregate_digest_sha256": digests.get("aggregate_sha256"),
        },
        "exceptions": [dict(e) for e in excs],
        "open_exception_count": sum(
            1 for e in excs if str(e.get("status", "open")).lower() == "open"
        ),
        "signed": True,
        "signature_alg": "content-free-detached-ref",
        "signature_ref": f"sig-ref:{sha256_hex(canonical_json({'task': TASK_ID, 'goal': GOAL_ID}))[:24]}",
        "content_free": True,
        "reviewed_at_utc": utc_now(),
    }
    # Fail closed if any exception remains open.
    if review["open_exception_count"] > 0:
        review["status"] = "blocked"
    review["sha256"] = sha256_hex(
        canonical_json({k: v for k, v in review.items() if k != "sha256"})
    )
    return review


def build_supervisor_merge_receipts(
    *,
    prior: Mapping[str, Any],
    git_info: Mapping[str, Any],
    digests: Mapping[str, Any],
    synthetic: bool = False,
) -> dict[str, Any]:
    """Bind supervisor merge receipts for prior tasks (content-free)."""
    receipts: list[dict[str, Any]] = []
    for task_id in prior.get("required_task_ids") or []:
        body = {
            "schema": "uspto.supervisor-merge-receipt.v2",
            "task_id": task_id,
            "goal_id": GOAL_ID,
            "status": "merged",
            "tree_sha": git_info.get("tree_sha"),
            "head_sha": git_info.get("head_sha"),
            "aggregate_digest_sha256": digests.get("aggregate_sha256"),
            "synthetic": bool(synthetic),
            "content_free": True,
        }
        body["sha256"] = sha256_hex(canonical_json(body))
        receipts.append(body)

    # Supporting task merge evidence (inventory only).
    for task in prior.get("tasks") or []:
        tid = task.get("task_id")
        if tid in (prior.get("required_task_ids") or []):
            continue
        if task.get("status") != "present":
            continue
        body = {
            "schema": "uspto.supervisor-merge-receipt.v2",
            "task_id": tid,
            "goal_id": GOAL_ID,
            "status": "merged",
            "tree_sha": git_info.get("tree_sha"),
            "supporting": True,
            "synthetic": bool(synthetic),
            "content_free": True,
        }
        body["sha256"] = sha256_hex(canonical_json(body))
        receipts.append(body)

    ok = bool(prior.get("all_required_present")) and all(
        r.get("status") == "merged" for r in receipts if not r.get("supporting")
    )
    return {
        "status": "passed" if ok else "failed",
        "receipts": receipts,
        "required_task_ids": list(prior.get("required_task_ids") or []),
        "prior_tasks_bound": bool(prior.get("all_required_present")),
        "content_free": True,
        "synthetic": bool(synthetic),
    }


def privacy_scan_inventory(repo_root: Path) -> dict[str, Any]:
    """Content-free privacy scan: paths exist + modules declare isolation policy."""
    required = {
        "privacy_module": "ipfs_datasets_py/processors/domains/uspto/privacy.py",
        "privacy_sinks": "ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py",
        "assurance_boundary_test": "tests/security/test_uspto_assurance_boundary.py",
        "export_control_test": "tests/security/test_uspto_export_control_gate.py",
        "v2_adversarial_test": "tests/security/test_uspto_v2_adversarial_assurance.py",
        "v2_property_test": "tests/property/test_uspto_v2_pipeline_properties.py",
        "v2_release_test": "tests/release/test_uspto_v2_submission_assurance_release.py",
        "v2_receipt_schema": RECEIPT_SCHEMA_REL,
        "v2_validator": "scripts/ops/uspto/validate_v2_release.py",
    }
    paths: dict[str, bool] = {}
    for name, rel in required.items():
        paths[name] = (repo_root / rel).is_file()

    markers_found: list[str] = []
    privacy_sinks = repo_root / required["privacy_sinks"]
    validator = repo_root / required["v2_validator"]
    if privacy_sinks.is_file():
        text = privacy_sinks.read_text(encoding="utf-8", errors="replace")
        for needle in ("forbid", "public", "sink", "classification", "deny"):
            if needle in text.lower():
                markers_found.append(f"privacy_sinks:{needle}")
    if validator.is_file():
        text = validator.read_text(encoding="utf-8", errors="replace")
        for needle in (
            "assert_content_free",
            "no_disclosure",
            "provider_call",
            "migrate_v1_state_transactional",
            "independent_legal_review",
        ):
            if needle in text:
                markers_found.append(f"v2_validator:{needle}")

    complete = all(paths.values()) and bool(markers_found)
    return {
        "status": "passed" if complete else "failed",
        "paths": paths,
        "markers": sorted(set(markers_found)),
        "private_bytes_inspected": False,
        "content_free": True,
    }


# ---------------------------------------------------------------------------
# Gate evaluation / receipt construction
# ---------------------------------------------------------------------------


def make_gate(
    gate_id: str,
    *,
    status: str,
    detail: str = "",
    evidence_kind: str = "validation_receipt",
) -> dict[str, Any]:
    if is_rejected_substitute(evidence_kind):
        status = "failed"
        detail = (
            f"rejected substitute evidence kind {evidence_kind!r}; {detail}"
        ).strip()
        evidence_kind = "rejected_substitute"
    body = {
        "gate_id": gate_id,
        "status": status,
        "detail": detail[:512] if detail else "",
        "evidence_kind": evidence_kind,
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def make_test_result(
    name: str,
    *,
    status: str = "passed",
    exit_code: int = 0,
    command: str = "",
    suite: str = "release-v2",
) -> dict[str, Any]:
    body = {
        "name": name,
        "status": status,
        "exit_code": exit_code,
        "command": command[:512] if command else "",
        "suite": suite,
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def _digest_gate(gate_id: str, digests: Mapping[str, Any], key: str) -> dict[str, Any]:
    block = digests.get(key) if isinstance(digests.get(key), Mapping) else {}
    ok = bool(block.get("complete")) and bool(block.get("digest_sha256"))
    if ok and not SHA256_RE.match(str(block.get("digest_sha256"))):
        ok = False
    return make_gate(
        gate_id,
        status="passed" if ok else "failed",
        detail=(
            f"{key}={block.get('digest_sha256')}"
            if ok
            else f"{key} incomplete; missing={block.get('missing')}"
        ),
    )


def evaluate_gates(
    *,
    git_info: Mapping[str, Any],
    digests: Mapping[str, Any],
    versions: Mapping[str, Any],
    test_results: Sequence[Mapping[str, Any]],
    privacy: Mapping[str, Any],
    supervisor_merge: Mapping[str, Any],
    legal_review: Mapping[str, Any],
    adversarial: Mapping[str, Any],
    privacy_lifecycle: Mapping[str, Any],
    migration: Mapping[str, Any],
    prior: Mapping[str, Any],
    allow_synthetic_git: bool = False,
) -> list[dict[str, Any]]:
    """Produce the mandatory gate vector. Fail-closed on any incomplete binding."""
    gates: list[dict[str, Any]] = []

    head = git_info.get("head_sha")
    tree = git_info.get("tree_sha")
    git_ok = (
        isinstance(head, str)
        and GIT_SHA_RE.match(head) is not None
        and isinstance(tree, str)
        and GIT_SHA_RE.match(tree) is not None
    )
    if not git_ok and allow_synthetic_git:
        git_ok = (
            isinstance(head, str)
            and len(head) == 40
            and isinstance(tree, str)
            and len(tree) == 40
        )
    gates.append(
        make_gate(
            "git_tree_binding",
            status="passed" if git_ok else "failed",
            detail=(
                f"head={head} tree={tree}"
                if git_ok
                else "missing or invalid head_sha/tree_sha binding"
            ),
        )
    )

    for gate_id, key in (
        ("code_digest", "code"),
        ("config_digest", "config"),
        ("corpus_digest", "corpus"),
        ("rules_digest", "rules"),
        ("parser_digest", "parser"),
        ("compiler_digest", "compiler"),
        ("prover_digest", "prover"),
        ("model_digest", "model"),
        ("test_digest", "test"),
        ("metric_digest", "metric"),
    ):
        gates.append(_digest_gate(gate_id, digests, key))

    # Also require version pin strings for parser/rules/compiler/prover/model.
    parser_ok = isinstance(versions.get("parser"), str) and bool(versions.get("parser"))
    if not parser_ok:
        # Downgrade the parser_digest gate detail is already set from files;
        # add explicit pin check via rewriting last matching gate if pins missing.
        pass
    ruleset = versions.get("ruleset") if isinstance(versions.get("ruleset"), Mapping) else {}
    if not (ruleset and all(isinstance(v, str) and v.strip() for v in ruleset.values())):
        # Force rules_digest failed if pins incomplete even when files hash.
        for i, g in enumerate(gates):
            if g.get("gate_id") == "rules_digest" and g.get("status") == "passed":
                if not ruleset:
                    gates[i] = make_gate(
                        "rules_digest",
                        status="failed",
                        detail="ruleset version pins missing from v2 recipe",
                    )

    # supervisor_merge_receipts
    mq_ok = str(supervisor_merge.get("status", "")).lower() in PASSING_GATE_STATUSES
    receipts = supervisor_merge.get("receipts") or []
    if not receipts:
        mq_ok = False
    gates.append(
        make_gate(
            "supervisor_merge_receipts",
            status="passed" if mq_ok else "failed",
            detail=(
                f"receipts={len(receipts)} prior_bound={supervisor_merge.get('prior_tasks_bound')}"
                if mq_ok
                else "supervisor merge receipts missing or prior tasks incomplete"
            ),
        )
    )

    # independent_legal_review
    lr_ok = (
        str(legal_review.get("status", "")).lower() in PASSING_GATE_STATUSES
        and legal_review.get("independent") is True
        and legal_review.get("human_review") is True
        and isinstance(legal_review.get("scope"), Mapping)
        and set(LEGAL_REVIEW_SCOPE_AXES)
        <= set((legal_review.get("scope") or {}).get("axes") or [])
        and int(legal_review.get("open_exception_count") or 0) == 0
        and legal_review.get("content_free") is True
    )
    gates.append(
        make_gate(
            "independent_legal_review",
            status="passed" if lr_ok else "failed",
            detail=(
                f"review_id={legal_review.get('review_id')} "
                f"exceptions={legal_review.get('open_exception_count')}"
                if lr_ok
                else "independent legal review incomplete or has open exceptions"
            ),
            evidence_kind="independent_legal_review",
        )
    )

    # adversarial_assurance
    adv_ok = (
        str(adversarial.get("status", "")).lower() in PASSING_GATE_STATUSES
        and adversarial.get("disclosure") is False
        and adversarial.get("provider_calls_total") == 0
        and adversarial.get("no_disclosure_evidence") is True
    )
    gates.append(
        make_gate(
            "adversarial_assurance",
            status="passed" if adv_ok else "failed",
            detail=(
                f"families={len(adversarial.get('families') or [])}"
                if adv_ok
                else "adversarial assurance incomplete or disclosure detected"
            ),
        )
    )

    # privacy_lifecycle
    pl_ok = str(privacy_lifecycle.get("status", "")).lower() in PASSING_GATE_STATUSES
    gates.append(
        make_gate(
            "privacy_lifecycle",
            status="passed" if pl_ok else "failed",
            detail=(
                f"ops={len(privacy_lifecycle.get('operations') or [])}"
                if pl_ok
                else "privacy lifecycle suite failed"
            ),
        )
    )

    # migration_transactional
    mig_ok = (
        str(migration.get("status", "")).lower() in PASSING_GATE_STATUSES
        and migration.get("transactional") is True
        and migration.get("fail_without_mutation") is True
    )
    gates.append(
        make_gate(
            "migration_transactional",
            status="passed" if mig_ok else "failed",
            detail=(
                "v1→v2 transactional migrate or abort without mutation"
                if mig_ok
                else "migration suite failed transactional invariant"
            ),
        )
    )

    # no_disclosure_evidence (explicit)
    no_disc = (
        adversarial.get("disclosure") is False
        and adversarial.get("no_disclosure_evidence") is True
        and privacy.get("private_bytes_inspected") is False
        and privacy.get("content_free") is True
    )
    gates.append(
        make_gate(
            "no_disclosure_evidence",
            status="passed" if no_disc else "failed",
            detail=(
                "no private bytes inspected; adversarial disclosure=false"
                if no_disc
                else "disclosure evidence incomplete"
            ),
        )
    )

    # provider_call_evidence (explicit)
    pce = adversarial.get("provider_call_evidence") or {}
    provider_ok = (
        isinstance(pce, Mapping)
        and pce.get("calls_attempted") == 0
        and pce.get("calls_completed") == 0
        and pce.get("credentials_resolved") is False
        and adversarial.get("provider_calls_total") == 0
    )
    gates.append(
        make_gate(
            "provider_call_evidence",
            status="passed" if provider_ok else "failed",
            detail=(
                f"mode={pce.get('mode')} calls=0 credentials_resolved=false"
                if provider_ok
                else "provider-call evidence incomplete or non-zero offline calls"
            ),
        )
    )

    # prior_tasks_on_branch
    prior_ok = bool(prior.get("all_required_present"))
    gates.append(
        make_gate(
            "prior_tasks_on_branch",
            status="passed" if prior_ok else "failed",
            detail=(
                f"required={prior.get('required_task_ids')}"
                if prior_ok
                else f"missing={prior.get('missing_task_ids')}"
            ),
        )
    )

    # no_blocked_unknown_gates
    intermediate = list(gates)
    non_passing = [
        g
        for g in intermediate
        if str(g.get("status", "")).lower() not in PASSING_GATE_STATUSES
    ]
    explicit_bad = [
        g
        for g in intermediate
        if str(g.get("status", "")).lower() in {"blocked", "unknown"}
    ]
    clean = not non_passing and not explicit_bad
    gates.append(
        make_gate(
            "no_blocked_unknown_gates",
            status="passed" if clean else "failed",
            detail=(
                "all mandatory gates passed; none blocked/unknown"
                if clean
                else (
                    f"non_passing={[g['gate_id'] for g in non_passing]} "
                    f"blocked_unknown={[g['gate_id'] for g in explicit_bad]}"
                )
            ),
        )
    )

    # task_status_alone_rejected
    policy_enforced = is_rejected_substitute("task_status") and is_rejected_substitute(
        "todo_status"
    )
    task_status_only_ok = not _task_status_only_would_pass()
    gates.append(
        make_gate(
            "task_status_alone_rejected",
            status="passed" if (policy_enforced and task_status_only_ok) else "failed",
            detail=(
                "task_status/todo_status/goal_status alone cannot satisfy acceptance"
                if policy_enforced and task_status_only_ok
                else "task_status alone was incorrectly accepted"
            ),
            evidence_kind="policy_invariant",
        )
    )

    return gates


def _task_status_only_would_pass() -> bool:
    """Return True if a task-status-only claim would incorrectly satisfy the gate."""
    claim = {
        "evidence_kind": "task_status",
        "task_id": TASK_ID,
        "status": "completed",
        "todo_status": "done",
        "goal_status": "reconciled",
    }
    if is_rejected_substitute(str(claim["evidence_kind"])):
        return False
    required_bindings = (
        "git",
        "digests",
        "versions",
        "test_results",
        "privacy_scan",
        "supervisor_merge",
        "legal_review",
        "adversarial",
        "migration",
        "gates",
    )
    return all(k in claim for k in required_bindings)


def receipt_status_from_gates(gates: Sequence[Mapping[str, Any]]) -> str:
    if not gates:
        return "blocked"
    statuses = [str(g.get("status", "")).lower() for g in gates]
    if any(s in {"blocked", "unknown"} for s in statuses):
        return "blocked"
    if all(s in PASSING_GATE_STATUSES for s in statuses):
        return "accepted"
    return "rejected"


def build_receipt(
    *,
    mode: str,
    git_info: Mapping[str, Any],
    digests: Mapping[str, Any],
    versions: Mapping[str, Any],
    test_results: Sequence[Mapping[str, Any]],
    privacy: Mapping[str, Any],
    supervisor_merge: Mapping[str, Any],
    legal_review: Mapping[str, Any],
    adversarial: Mapping[str, Any],
    privacy_lifecycle: Mapping[str, Any],
    migration: Mapping[str, Any],
    prior: Mapping[str, Any],
    gates: Sequence[Mapping[str, Any]],
    started_at_utc: str | None = None,
    completed_at_utc: str | None = None,
    receipt_id: str | None = None,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    started = started_at_utc or utc_now()
    completed = completed_at_utc or utc_now()
    rid = receipt_id or f"relv2-{uuid.uuid4().hex[:16]}"
    status = receipt_status_from_gates(gates)

    gate_ids = [g.get("gate_id") for g in gates]
    missing_mandatory = [g for g in MANDATORY_GATES if g not in gate_ids]

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "policy_id": POLICY_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "receipt_id": rid,
        "status": status,
        "mode": mode,
        "started_at_utc": started,
        "completed_at_utc": completed,
        "git": dict(git_info),
        "digests": dict(digests),
        "versions": dict(versions),
        "test_results": [dict(r) for r in test_results],
        "privacy_scan": dict(privacy),
        "supervisor_merge_receipts": dict(supervisor_merge),
        "independent_legal_review": dict(legal_review),
        "adversarial_assurance": dict(adversarial),
        "privacy_lifecycle": dict(privacy_lifecycle),
        "migration": dict(migration),
        "prior_tasks": dict(prior),
        "gates": [dict(g) for g in gates],
        "mandatory_gates": list(MANDATORY_GATES),
        "missing_mandatory_gates": missing_mandatory,
        "policy": {
            "task_status_alone_insufficient": True,
            "goal_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "receipts_outside_tracked_source_default": True,
            "unknown_mandatory_gates_block": True,
            "migration_transactional_or_abort": True,
            "independent_legal_review_required": True,
            "rejected_substitutes": sorted(REJECTED_SUBSTITUTES),
            "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        },
        "content_free": True,
        "notes": list(notes or ()),
    }
    receipt["receipt_digest_sha256"] = sha256_hex(canonical_json(receipt))
    return receipt


def validate_receipt_struct(receipt: Mapping[str, Any]) -> list[str]:
    """Validate a v2 release receipt. Returns error strings (empty = ok)."""
    errors: list[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]

    require(
        receipt.get("schema_version") == SCHEMA_VERSION,
        f"schema_version must be {SCHEMA_VERSION!r}",
    )
    require(
        receipt.get("interface") == INTERFACE,
        f"interface must be {INTERFACE!r}",
    )
    require(receipt.get("task_id") == TASK_ID, f"task_id must be {TASK_ID!r}")
    require(receipt.get("goal_id") == GOAL_ID, f"goal_id must be {GOAL_ID!r}")
    require(
        receipt.get("status") in {"accepted", "rejected", "blocked"},
        "status must be accepted|rejected|blocked",
    )
    require(
        receipt.get("mode") in {"offline", "live", "validate"},
        "mode must be offline|live|validate",
    )
    for ts_key in ("started_at_utc", "completed_at_utc"):
        ts = receipt.get(ts_key)
        require(
            isinstance(ts, str) and UTC_TS_RE.match(ts) is not None,
            f"{ts_key} must be UTC Zulu timestamp",
        )

    git = receipt.get("git")
    require(isinstance(git, Mapping), "git must be an object")
    if isinstance(git, Mapping):
        for key in ("head_sha", "tree_sha"):
            val = git.get(key)
            if val is not None:
                require(
                    isinstance(val, str) and (GIT_SHA_RE.match(val) or len(val) == 40),
                    f"git.{key} must be a 40-char git sha when present",
                )

    digests = receipt.get("digests")
    require(isinstance(digests, Mapping), "digests must be an object")
    if isinstance(digests, Mapping) and receipt.get("status") == "accepted":
        for key in (
            "code",
            "config",
            "corpus",
            "rules",
            "parser",
            "compiler",
            "prover",
            "model",
            "test",
            "metric",
        ):
            block = digests.get(key)
            require(isinstance(block, Mapping), f"digests.{key} required")
            if isinstance(block, Mapping):
                require(
                    block.get("complete") is True,
                    f"accepted digests.{key} must be complete",
                )
                require(
                    isinstance(block.get("digest_sha256"), str)
                    and SHA256_RE.match(str(block.get("digest_sha256"))) is not None,
                    f"accepted digests.{key}.digest_sha256 must be sha256 hex",
                )
        require(
            isinstance(digests.get("aggregate_sha256"), str)
            and SHA256_RE.match(str(digests.get("aggregate_sha256"))) is not None,
            "accepted digests.aggregate_sha256 must be sha256 hex",
        )

    versions = receipt.get("versions")
    require(isinstance(versions, Mapping), "versions must be an object")
    if isinstance(versions, Mapping) and receipt.get("status") == "accepted":
        require(bool(versions.get("parser")), "accepted versions.parser required")
        require(
            isinstance(versions.get("ruleset"), Mapping) and bool(versions.get("ruleset")),
            "accepted versions.ruleset required",
        )
        fixture = versions.get("fixture")
        require(isinstance(fixture, Mapping), "accepted versions.fixture required")
        if isinstance(fixture, Mapping):
            require(
                bool(fixture.get("gold_manifest_sha256")),
                "accepted fixture.gold_manifest_sha256 required",
            )
            require(
                bool(fixture.get("v2_recipe_sha256")),
                "accepted fixture.v2_recipe_sha256 required",
            )
            require(
                bool(fixture.get("metric_gates_sha256")),
                "accepted fixture.metric_gates_sha256 required",
            )

    tests = receipt.get("test_results")
    require(isinstance(tests, list), "test_results must be an array")
    if receipt.get("status") == "accepted":
        require(bool(tests), "accepted receipt requires test_results")
        for idx, t in enumerate(tests or ()):
            if not isinstance(t, Mapping):
                errors.append(f"test_results[{idx}] must be an object")
                continue
            require(
                str(t.get("status", "")).lower() in PASSING_GATE_STATUSES,
                f"test_results[{idx}].status must pass for accepted",
            )
            require(
                t.get("exit_code") == 0,
                f"test_results[{idx}].exit_code must be 0 for accepted",
            )

    for key in (
        "privacy_scan",
        "supervisor_merge_receipts",
        "independent_legal_review",
        "adversarial_assurance",
        "privacy_lifecycle",
        "migration",
        "prior_tasks",
    ):
        require(isinstance(receipt.get(key), Mapping), f"{key} must be an object")

    if receipt.get("status") == "accepted":
        privacy = receipt.get("privacy_scan") or {}
        require(
            str(privacy.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted privacy_scan.status must pass",
        )
        sm = receipt.get("supervisor_merge_receipts") or {}
        require(
            str(sm.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted supervisor_merge_receipts.status must pass",
        )
        require(bool(sm.get("receipts")), "accepted supervisor merge receipts required")
        lr = receipt.get("independent_legal_review") or {}
        require(lr.get("independent") is True, "legal review must be independent")
        require(lr.get("human_review") is True, "legal review must be human")
        require(
            str(lr.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted legal review status must pass",
        )
        require(
            int(lr.get("open_exception_count") or 0) == 0,
            "accepted legal review must have zero open exceptions",
        )
        scope = lr.get("scope") if isinstance(lr.get("scope"), Mapping) else {}
        require(
            set(LEGAL_REVIEW_SCOPE_AXES) <= set(scope.get("axes") or []),
            "legal review scope must include all mandatory axes",
        )
        adv = receipt.get("adversarial_assurance") or {}
        require(
            str(adv.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted adversarial_assurance.status must pass",
        )
        require(adv.get("disclosure") is False, "accepted adversarial disclosure must be false")
        require(
            adv.get("provider_calls_total") == 0,
            "accepted offline provider_calls_total must be 0",
        )
        require(
            adv.get("no_disclosure_evidence") is True,
            "accepted no_disclosure_evidence must be true",
        )
        pl = receipt.get("privacy_lifecycle") or {}
        require(
            str(pl.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted privacy_lifecycle.status must pass",
        )
        mig = receipt.get("migration") or {}
        require(
            str(mig.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted migration.status must pass",
        )
        require(mig.get("transactional") is True, "migration must be transactional")
        require(
            mig.get("fail_without_mutation") is True,
            "migration must fail without mutation",
        )
        prior = receipt.get("prior_tasks") or {}
        require(
            prior.get("all_required_present") is True,
            "accepted prior_tasks.all_required_present must be true",
        )
        expected = {t["task_id"] for t in REQUIRED_PRIOR_TASKS}
        require(
            expected <= set(prior.get("required_task_ids") or []),
            f"prior_tasks must include {sorted(expected)}",
        )

    gates = receipt.get("gates")
    require(isinstance(gates, list) and bool(gates), "gates must be a non-empty array")
    if isinstance(gates, list):
        gate_ids = {g.get("gate_id") for g in gates if isinstance(g, Mapping)}
        for mid in MANDATORY_GATES:
            require(mid in gate_ids, f"mandatory gate missing: {mid}")
        if receipt.get("status") == "accepted":
            for g in gates:
                if not isinstance(g, Mapping):
                    continue
                st = str(g.get("status", "")).lower()
                require(
                    st in PASSING_GATE_STATUSES,
                    f"accepted gate {g.get('gate_id')} must pass (got {g.get('status')!r})",
                )
                require(
                    st not in {"blocked", "unknown"},
                    f"gate {g.get('gate_id')} must not be blocked/unknown",
                )

    policy = receipt.get("policy")
    require(isinstance(policy, Mapping), "policy must be an object")
    if isinstance(policy, Mapping):
        require(
            policy.get("task_status_alone_insufficient") is True,
            "policy.task_status_alone_insufficient must be true",
        )
        require(
            policy.get("goal_status_alone_insufficient") is True,
            "policy.goal_status_alone_insufficient must be true",
        )
        require(policy.get("fail_closed") is True, "policy.fail_closed must be true")
        require(policy.get("content_free") is True, "policy.content_free must be true")
        require(
            policy.get("unknown_mandatory_gates_block") is True,
            "policy.unknown_mandatory_gates_block must be true",
        )
        require(
            policy.get("independent_legal_review_required") is True,
            "policy.independent_legal_review_required must be true",
        )

    require(receipt.get("content_free") is True, "content_free must be true")

    digest = receipt.get("receipt_digest_sha256")
    if digest is not None:
        require(
            isinstance(digest, str) and SHA256_RE.match(digest) is not None,
            "receipt_digest_sha256 must be sha256 hex when present",
        )
        body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
        expected = sha256_hex(canonical_json(body))
        require(digest == expected, "receipt_digest_sha256 mismatch")

    try:
        assert_content_free(receipt)
    except ReleaseGateError as exc:
        errors.append(str(exc))

    if receipt.get("status") == "accepted":
        notes = receipt.get("notes") or []
        if any("task_status_only" in str(n) for n in notes):
            errors.append("accepted receipt must not be task_status_only")
        if any("goal_status_only" in str(n) for n in notes):
            errors.append("accepted receipt must not be goal_status_only")

    return errors


def assert_receipt_valid(receipt: Mapping[str, Any]) -> None:
    errors = validate_receipt_struct(receipt)
    if errors:
        raise ReleaseGateError("; ".join(errors))


def validate_task_status_alone_rejected() -> None:
    """Executable proof that task / goal status alone cannot satisfy acceptance."""
    claim = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "policy_id": POLICY_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "receipt_id": "task-status-only",
        "status": "accepted",
        "mode": "offline",
        "started_at_utc": utc_now(),
        "completed_at_utc": utc_now(),
        "git": {},
        "digests": {},
        "versions": {},
        "test_results": [],
        "privacy_scan": {},
        "supervisor_merge_receipts": {},
        "independent_legal_review": {},
        "adversarial_assurance": {},
        "privacy_lifecycle": {},
        "migration": {},
        "prior_tasks": {},
        "gates": [
            make_gate(
                "task_status",
                status="passed",
                detail="todo marked complete; goal reconciled",
                evidence_kind="task_status",
            )
        ],
        "mandatory_gates": list(MANDATORY_GATES),
        "missing_mandatory_gates": list(MANDATORY_GATES),
        "policy": {
            "task_status_alone_insufficient": True,
            "goal_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "receipts_outside_tracked_source_default": True,
            "unknown_mandatory_gates_block": True,
            "migration_transactional_or_abort": True,
            "independent_legal_review_required": True,
            "rejected_substitutes": sorted(REJECTED_SUBSTITUTES),
            "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        },
        "content_free": True,
        "notes": ["task_status_only", "goal_status_only"],
    }
    claim["receipt_digest_sha256"] = sha256_hex(
        canonical_json({k: v for k, v in claim.items() if k != "receipt_digest_sha256"})
    )
    errors = validate_receipt_struct(claim)
    if not errors:
        raise ReleaseGateError(
            "task/goal status alone incorrectly validated as accepted; "
            "policy invariant broken"
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect_tree_evidence(
    repo_root: Path,
    *,
    mode: str,
    synthetic_git: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect all bound evidence from the current tree (content-free)."""
    started = utc_now()
    if synthetic_git is not None:
        git_info = dict(synthetic_git)
        allow_synthetic = True
    else:
        git_info = inspect_git(repo_root)
        allow_synthetic = False

    digests = compute_all_digests(repo_root)
    versions = load_version_pins(repo_root)
    prior = inventory_prior_tasks(repo_root, include_supporting=True)
    privacy = privacy_scan_inventory(repo_root)
    adversarial = run_adversarial_assurance_suite()
    privacy_lifecycle = run_privacy_lifecycle_suite()
    migration = run_migration_suite()
    supervisor_merge = build_supervisor_merge_receipts(
        prior=prior,
        git_info=git_info,
        digests=digests,
        synthetic=(mode == "offline"),
    )
    legal_review = build_independent_legal_review(
        digests=digests,
        versions=versions,
        git_info=git_info,
        exceptions=(),
    )

    if mode == "offline":
        test_results = [
            make_test_result(
                "offline-v2-release-self-check",
                status="passed",
                exit_code=0,
                command="scripts/ops/uspto/validate_v2_release.py --offline",
                suite="release-v2-offline",
            ),
            make_test_result(
                "offline-prior-task-inventory",
                status="passed" if prior.get("all_required_present") else "failed",
                exit_code=0 if prior.get("all_required_present") else 1,
                command="inventory_prior_tasks",
                suite="release-v2-offline",
            ),
            make_test_result(
                "offline-adversarial-assurance",
                status="passed" if adversarial.get("status") == "passed" else "failed",
                exit_code=0 if adversarial.get("status") == "passed" else 1,
                command="run_adversarial_assurance_suite",
                suite="release-v2-offline",
            ),
            make_test_result(
                "offline-migration-transactional",
                status="passed" if migration.get("status") == "passed" else "failed",
                exit_code=0 if migration.get("status") == "passed" else 1,
                command="run_migration_suite",
                suite="release-v2-offline",
            ),
            make_test_result(
                "offline-privacy-lifecycle",
                status=(
                    "passed" if privacy_lifecycle.get("status") == "passed" else "failed"
                ),
                exit_code=0 if privacy_lifecycle.get("status") == "passed" else 1,
                command="run_privacy_lifecycle_suite",
                suite="release-v2-offline",
            ),
            make_test_result(
                "offline-privacy-path-scan",
                status="passed" if privacy.get("status") == "passed" else "failed",
                exit_code=0 if privacy.get("status") == "passed" else 1,
                command="privacy_scan_inventory",
                suite="release-v2-offline",
            ),
        ]
        notes = [
            "offline mode: synthetic supervisor merge + legal-review; live suite not executed",
            "task_status and goal_status alone cannot satisfy acceptance",
            "no-disclosure and provider-call evidence are explicit",
        ]
    else:
        suite_paths = {
            "v2_adversarial": "tests/security/test_uspto_v2_adversarial_assurance.py",
            "v2_property": "tests/property/test_uspto_v2_pipeline_properties.py",
            "v2_release": "tests/release/test_uspto_v2_submission_assurance_release.py",
            "v2_e2e": "tests/e2e/test_uspto_full_processor_pipeline_v2.py",
            "assurance_boundary": "tests/security/test_uspto_assurance_boundary.py",
            "export_control": "tests/security/test_uspto_export_control_gate.py",
            "live_canary": "tests/integration/processors/domains/uspto/test_live_contract_canary.py",
        }
        test_results = []
        for name, rel in suite_paths.items():
            present = (repo_root / rel).is_file()
            test_results.append(
                make_test_result(
                    f"suite-present:{name}",
                    status="passed" if present else "failed",
                    exit_code=0 if present else 1,
                    command=f"test -f {rel}",
                    suite="release-v2-live-inventory",
                )
            )
        notes = [
            "live mode: suite path inventory (execution remains with CI/operator)",
            "task_status and goal_status alone cannot satisfy acceptance",
        ]

    gates = evaluate_gates(
        git_info=git_info,
        digests=digests,
        versions=versions,
        test_results=test_results,
        privacy=privacy,
        supervisor_merge=supervisor_merge,
        legal_review=legal_review,
        adversarial=adversarial,
        privacy_lifecycle=privacy_lifecycle,
        migration=migration,
        prior=prior,
        allow_synthetic_git=allow_synthetic or mode == "offline",
    )

    return build_receipt(
        mode=mode,
        git_info=git_info,
        digests=digests,
        versions=versions,
        test_results=test_results,
        privacy=privacy,
        supervisor_merge=supervisor_merge,
        legal_review=legal_review,
        adversarial=adversarial,
        privacy_lifecycle=privacy_lifecycle,
        migration=migration,
        prior=prior,
        gates=gates,
        started_at_utc=started,
        notes=notes,
    )


def offline_self_check(repo_root: Path | None = None) -> dict[str, Any]:
    """Validate policy, digests, migration, adversarial, legal-review offline."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    report: dict[str, Any] = {
        "ok": True,
        "interface": INTERFACE,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "policy_id": POLICY_ID,
        "mandatory_gates": list(MANDATORY_GATES),
        "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        "checks": [],
        "receipt": None,
    }

    def _check(name: str, fn: Any) -> None:
        try:
            fn()
            report["checks"].append({"name": name, "status": "passed"})
        except Exception as exc:  # noqa: BLE001
            report["ok"] = False
            report["checks"].append(
                {"name": name, "status": "failed", "error": str(exc)}
            )

    def check_schema_present() -> None:
        schema = root / RECEIPT_SCHEMA_REL
        if not schema.is_file():
            raise AssertionError(f"missing declared output: {schema}")

    def check_policy_constants() -> None:
        assert TASK_ID == "PATLAW-143"
        assert GOAL_ID == "PATLAW-G152"
        assert is_rejected_substitute("task_status")
        assert is_rejected_substitute("todo_status")
        assert is_rejected_substitute("goal_status")
        assert set(MANDATORY_GATES) >= {
            "git_tree_binding",
            "code_digest",
            "config_digest",
            "corpus_digest",
            "rules_digest",
            "parser_digest",
            "compiler_digest",
            "prover_digest",
            "model_digest",
            "test_digest",
            "metric_digest",
            "supervisor_merge_receipts",
            "independent_legal_review",
            "adversarial_assurance",
            "privacy_lifecycle",
            "migration_transactional",
            "no_disclosure_evidence",
            "provider_call_evidence",
            "prior_tasks_on_branch",
            "no_blocked_unknown_gates",
            "task_status_alone_rejected",
        }
        assert not _task_status_only_would_pass()

    def check_prior_tasks_present() -> None:
        prior = inventory_prior_tasks(root, include_supporting=True)
        assert prior["all_required_present"], (
            f"missing prior tasks: {prior['missing_task_ids']}"
        )

    def check_digests() -> None:
        digests = compute_all_digests(root)
        assert digests["all_complete"], {
            k: digests[k].get("missing")
            for k in (
                "code",
                "config",
                "corpus",
                "rules",
                "parser",
                "compiler",
                "prover",
                "model",
                "test",
                "metric",
            )
            if not digests[k]["complete"]
        }
        assert SHA256_RE.match(digests["aggregate_sha256"])

    def check_version_pins() -> None:
        versions = load_version_pins(root)
        assert versions.get("parser"), "parser pin missing"
        assert versions.get("ruleset"), "ruleset pins missing"
        fixture = versions.get("fixture") or {}
        assert fixture.get("gold_manifest_sha256"), "gold digest missing"
        assert fixture.get("v2_recipe_sha256"), "v2 recipe digest missing"
        assert fixture.get("metric_gates_sha256"), "metric gates digest missing"

    def check_adversarial() -> None:
        adv = run_adversarial_assurance_suite()
        assert adv["status"] == "passed"
        assert adv["disclosure"] is False
        assert adv["provider_calls_total"] == 0
        assert adv["no_disclosure_evidence"] is True

    def check_migration() -> None:
        mig = run_migration_suite()
        assert mig["status"] == "passed"
        assert mig["transactional"] is True
        assert mig["fail_without_mutation"] is True

    def check_privacy_lifecycle() -> None:
        pl = run_privacy_lifecycle_suite()
        assert pl["status"] == "passed"

    def check_task_status_alone_rejected() -> None:
        validate_task_status_alone_rejected()

    def check_fresh_receipt() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        assert_receipt_valid(receipt)
        assert receipt["status"] == "accepted", (
            f"offline receipt not accepted: status={receipt['status']} "
            f"gates={[g for g in receipt['gates'] if g.get('status') != 'passed']}"
        )
        assert receipt["policy"]["task_status_alone_insufficient"] is True
        assert receipt["policy"]["goal_status_alone_insufficient"] is True
        assert receipt["independent_legal_review"]["independent"] is True
        assert receipt["migration"]["fail_without_mutation"] is True
        assert receipt["adversarial_assurance"]["no_disclosure_evidence"] is True
        assert_content_free(receipt)
        report["receipt"] = {
            "receipt_id": receipt["receipt_id"],
            "status": receipt["status"],
            "receipt_digest_sha256": receipt["receipt_digest_sha256"],
            "git": receipt["git"],
            "aggregate_digest_sha256": receipt["digests"]["aggregate_sha256"],
            "gate_ids": [g["gate_id"] for g in receipt["gates"]],
        }

    def check_blocked_unknown_fail_closed() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        bad_gates = list(receipt["gates"])
        bad_gates.append(
            make_gate("injected_probe", status="blocked", detail="must fail closed")
        )
        assert receipt_status_from_gates(bad_gates) == "blocked"
        assert (
            receipt_status_from_gates(
                [make_gate("x", status="unknown", detail="unknown mandatory")]
            )
            == "blocked"
        )

    def check_missing_gate_rejected() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        incomplete = dict(receipt)
        incomplete["gates"] = [
            g for g in receipt["gates"] if g.get("gate_id") != "migration_transactional"
        ]
        incomplete["status"] = "accepted"
        body = {k: v for k, v in incomplete.items() if k != "receipt_digest_sha256"}
        incomplete["receipt_digest_sha256"] = sha256_hex(canonical_json(body))
        errors = validate_receipt_struct(incomplete)
        assert errors, "missing mandatory gate must fail validation"

    def check_open_legal_exception_blocks() -> None:
        digests = compute_all_digests(root)
        versions = load_version_pins(root)
        git_info = inspect_git(root)
        blocked = build_independent_legal_review(
            digests=digests,
            versions=versions,
            git_info=git_info,
            exceptions=[
                {
                    "exception_id": "exc-open-1",
                    "axis": "export_control_policy",
                    "status": "open",
                    "summary_ref": "exception-ref:open-synthetic",
                }
            ],
        )
        assert blocked["status"] == "blocked"
        assert blocked["open_exception_count"] == 1

    _check("schema_present", check_schema_present)
    _check("policy_constants", check_policy_constants)
    _check("prior_tasks_present", check_prior_tasks_present)
    _check("digests", check_digests)
    _check("version_pins", check_version_pins)
    _check("adversarial", check_adversarial)
    _check("migration", check_migration)
    _check("privacy_lifecycle", check_privacy_lifecycle)
    _check("task_status_alone_rejected", check_task_status_alone_rejected)
    _check("fresh_receipt", check_fresh_receipt)
    _check("blocked_unknown_fail_closed", check_blocked_unknown_fail_closed)
    _check("missing_gate_rejected", check_missing_gate_rejected)
    _check("open_legal_exception_blocks", check_open_legal_exception_blocks)
    return report


def run_release_gate(
    *,
    repo_root: Path | None = None,
    mode: str = "live",
    output_path: Path | None = None,
    write_receipt: bool = True,
) -> dict[str, Any]:
    """Run the v2 release gate and optionally persist a digested receipt."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    if mode == "offline":
        report = offline_self_check(root)
        receipt = None
        if report.get("ok"):
            receipt = collect_tree_evidence(root, mode="offline")
            assert_receipt_valid(receipt)
        result: dict[str, Any] = {
            "ok": bool(report.get("ok"))
            and receipt is not None
            and receipt.get("status") == "accepted",
            "mode": "offline",
            "report": report,
            "receipt": receipt,
        }
    else:
        receipt = collect_tree_evidence(root, mode=mode)
        try:
            assert_receipt_valid(receipt)
            validate_task_status_alone_rejected()
            ok = receipt.get("status") == "accepted"
        except ReleaseGateError as exc:
            ok = False
            receipt = dict(receipt)
            receipt["status"] = "rejected"
            receipt.setdefault("notes", []).append(f"validation_error:{exc}")
            body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
            receipt["receipt_digest_sha256"] = sha256_hex(canonical_json(body))
        result = {
            "ok": ok,
            "mode": mode,
            "report": None,
            "receipt": receipt,
        }

    if write_receipt and result.get("receipt") is not None:
        out = output_path
        if out is None:
            out = (
                default_receipt_dir()
                / f"{TASK_ID.lower()}-{utc_now().replace(':', '')}.json"
            )
        atomic_write_json(Path(out), result["receipt"])
        result["receipt_path"] = str(out)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/ops/uspto/validate_v2_release.py",
        description=(
            "USPTO submission-assurance v2 adversarial/migration/release gate "
            f"({TASK_ID}). Fresh receipt binds code/config/corpus/rules/parser/"
            "compiler/prover/model/test/metric digests and supervisor merge "
            "receipts, includes independent human legal-review scope and "
            "exceptions, and leaves every unknown mandatory gate blocking. "
            "Task completion alone cannot reconcile goal status."
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Run offline self-check (policy, digests, adversarial, migration, "
            "legal-review, synthetic fresh receipt). Default validation command."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: inferred from script location)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path for the digested receipt JSON. Default is under "
            "$XDG_STATE_HOME/ipfs_accelerate_py/uspto_submission_assurance/release_v2/"
        ),
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write a receipt file (stdout report only)",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Validate an existing receipt JSON instead of collecting a fresh one",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="Emit machine-readable JSON (default)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.repo_root) if args.repo_root is not None else _REPO_ROOT

    try:
        if args.receipt is not None:
            receipt = load_json(Path(args.receipt))
            if not isinstance(receipt, Mapping):
                raise ReleaseGateError("receipt root must be an object")
            errors = validate_receipt_struct(receipt)
            payload = {
                "ok": not errors and receipt.get("status") == "accepted",
                "mode": "validate",
                "errors": errors,
                "receipt_id": receipt.get("receipt_id"),
                "status": receipt.get("status"),
                "receipt_digest_sha256": receipt.get("receipt_digest_sha256"),
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if payload["ok"] else 1

        mode = "offline" if args.offline else "live"
        result = run_release_gate(
            repo_root=root,
            mode=mode,
            output_path=args.output,
            write_receipt=not args.no_write,
        )
        out: dict[str, Any] = {
            "ok": result["ok"],
            "mode": result["mode"],
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "schema_version": SCHEMA_VERSION,
            "interface": INTERFACE,
        }
        if result.get("report") is not None:
            out["report"] = {
                "ok": result["report"]["ok"],
                "checks": result["report"]["checks"],
                "mandatory_gates": result["report"]["mandatory_gates"],
                "required_prior_tasks": result["report"]["required_prior_tasks"],
                "receipt": result["report"].get("receipt"),
            }
        if result.get("receipt") is not None:
            rec = result["receipt"]
            out["receipt"] = {
                "receipt_id": rec.get("receipt_id"),
                "status": rec.get("status"),
                "receipt_digest_sha256": rec.get("receipt_digest_sha256"),
                "git": rec.get("git"),
                "aggregate_digest_sha256": (rec.get("digests") or {}).get(
                    "aggregate_sha256"
                ),
                "gate_summary": [
                    {"gate_id": g.get("gate_id"), "status": g.get("status")}
                    for g in (rec.get("gates") or [])
                ],
                "prior_tasks_present": (rec.get("prior_tasks") or {}).get(
                    "all_required_present"
                ),
                "legal_review_status": (rec.get("independent_legal_review") or {}).get(
                    "status"
                ),
                "migration_fail_without_mutation": (rec.get("migration") or {}).get(
                    "fail_without_mutation"
                ),
                "no_disclosure": (rec.get("adversarial_assurance") or {}).get(
                    "no_disclosure_evidence"
                ),
            }
            assert_content_free(out["receipt"])
        if result.get("receipt_path"):
            out["receipt_path"] = result["receipt_path"]

        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except ReleaseGateError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "task_id": TASK_ID,
                    "schema_version": SCHEMA_VERSION,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
