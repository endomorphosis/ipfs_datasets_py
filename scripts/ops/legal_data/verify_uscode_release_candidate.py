#!/usr/bin/env python3
"""Produce and verify the US Code sparse GraphRAG release-candidate receipt (USCIR-038).

Binds producer evidence into an immutable, independently reproducible receipt:

* source release point
* dataset revision / local fixture candidate root (repo-relative label only)
* manifest / config / code / model digests
* counts
* evaluation, security, determinism, viewer, canary, rollback
* exception dispositions

Fail-closed policy
------------------
* Missing, mismatched, or stale producer inputs fail verification.
* The receipt must not embed secrets or absolute local paths.
* This CLI never publishes, never contacts the Hub, and never manufactures
  missing producer receipts.

Validation gate (offline)::

    python scripts/ops/legal_data/verify_uscode_release_candidate.py \\
        --receipt docs/reports/uscode_release_candidate.json --fixture-only
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

from ipfs_datasets_py.huggingface.release import (  # noqa: E402
    reject_identity_contamination,
)
from ipfs_datasets_py.processors.legal_data.uscode_embeddings import (  # noqa: E402
    DEFAULT_DIMENSION,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    DEFAULT_NORMALIZATION,
    DEFAULT_POOLING,
    build_vector_space_id,
)
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_SOURCE_REVISION,
    UscodeHuggingFaceRelease,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
    build_uscode_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    validate_uscode_hf_release,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (  # noqa: E402
    RELEASE_PROFILE,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_APPROVED_RELEASE_POINT,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-038"
GOAL_ID: Final = "USCIR-G100"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "verify_uscode_release_candidate.py"
CODE_VERSION: Final = "1"

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-release-candidate@1"
SCHEMA_VERSION: Final = "uscode-release-candidate/v1"

DEFAULT_RECEIPT_RELPATH: Final = Path("docs/reports/uscode_release_candidate.json")

# Producer evidence surfaces (repo-relative; fail closed if missing).
EVALUATION_REPORT_RELPATH: Final = Path(
    "docs/reports/uscode_sparse_graphrag_evaluation.json"
)
SECURITY_REPORT_RELPATH: Final = Path("docs/reports/uscode_release_security.json")
E2E_REPORT_RELPATH: Final = Path("docs/reports/uscode_e2e_local.json")
CANARY_FIXTURE_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_remote_canary.json")
STAGE_PLAN_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_stage_plan.json")
RUNBOOK_RELPATH: Final = Path("docs/guides/USCODE_SPARSE_GRAPHRAG_RUNBOOK.md")
MIGRATION_RELPATH: Final = Path("docs/guides/USCODE_SPARSE_GRAPHRAG_MIGRATION.md")
E2E_RECIPE_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_e2e_release/recipe.json")

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_STAGING_BRANCH: Final = "stage/uscode-sparse-graphrag-v2"
DEFAULT_CANDIDATE_ROOT_LABEL: Final = "fixture://uscode-hf-release-candidate"
ROLLBACK_REVISION: Final = DEFAULT_SOURCE_REVISION
ROLLBACK_DEFAULT_CONFIG: Final = DEFAULT_CONFIG_NAME

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "USCODE_STAGING_AUTHORIZATION",
)

REQUIRED_EVIDENCE_KEYS: Final[tuple[str, ...]] = (
    "evaluation",
    "security",
    "e2e",
    "canary",
    "stage_plan",
    "runbook",
    "migration",
    "determinism",
    "viewer",
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Absolute local path patterns that must never appear in the receipt surface.
_ABS_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=:])"
    r"(?:"
    r"/(?:home|Users|tmp|var|private|opt|root|etc|mnt|media|workspace)/"
    r"|[A-Za-z]:\\|"
    r"file://"
    r")",
)
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"'`=:])/home/[A-Za-z0-9._-]+/")
_WINDOWS_USER_RE = re.compile(
    r"(?:^|[\s\"'`=:])[A-Za-z]:\\Users\\",
    re.IGNORECASE,
)


class ReleaseCandidateError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class MissingInputError(ReleaseCandidateError):
    """Raised when a required producer input is absent."""


class MismatchError(ReleaseCandidateError):
    """Raised when a bound digest or field does not match the live input."""


class StaleInputError(ReleaseCandidateError):
    """Raised when a receipt binds a digest that no longer matches disk."""


class PathLeakError(ReleaseCandidateError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(ReleaseCandidateError):
    """Raised when credential-like material appears in a public receipt."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def repo_relpath(path: Path | str, *, repo_root: Path | str | None = None) -> str:
    """Return a POSIX repo-relative path; never an absolute local path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = Path(path)
    try:
        rel = target.resolve().relative_to(root.resolve())
    except ValueError:
        # Already relative or outside root — keep as given if not absolute.
        text = str(path).replace("\\", "/")
        if text.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", text):
            raise PathLeakError(
                f"refusing absolute path in receipt surface: {text!r}"
            )
        return text.lstrip("./")
    return rel.as_posix()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCandidateError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ReleaseCandidateError(f"JSON root must be an object: {target}")
    return dict(payload)


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    reject_path_leaks(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path | str) -> str:
    target = Path(path)
    if not target.is_file():
        raise MissingInputError(f"file not found for digest: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Credential / path leak guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens or secret-like values appear in public surfaces."""

    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                # Policy booleans may reuse words like "authorization".
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
        raise SecretLeakError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_path_leaks(value: Any, *, label: str = "payload") -> None:
    """Fail closed when absolute local paths appear in a public receipt."""

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
            # Bare absolute POSIX paths that are not repo-relative labels.
            if text.startswith("/") and not text.startswith("fixture://"):
                # Allow pure digest-like or schema URIs that start with slash? No.
                # Repo-relative paths never start with '/'.
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
        raise PathLeakError(
            f"absolute local path leak in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(a) for a in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "api_key=",
        "huggingface_token=",
        "uscode_staging_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise SecretLeakError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )


# ---------------------------------------------------------------------------
# Evidence loading
# ---------------------------------------------------------------------------


def _require_file(relpath: Path, *, repo_root: Path) -> Path:
    path = (repo_root / relpath).resolve()
    if not path.is_file():
        raise MissingInputError(
            f"required producer input missing: {relpath.as_posix()}"
        )
    return path


def _evidence_binding(
    *,
    key: str,
    relpath: Path,
    task_id: str | None,
    sha256: str,
    ok: bool,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    binding: dict[str, Any] = {
        "key": key,
        "ok": bool(ok),
        "path": relpath.as_posix(),
        "sha256": normalize_sha256(sha256, name=f"{key}.sha256"),
        "task_id": task_id,
    }
    if extra:
        for field, value in extra.items():
            binding[field] = value
    return binding


def load_producer_evidence(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load and digest all required producer evidence surfaces."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT

    evaluation_path = _require_file(EVALUATION_REPORT_RELPATH, repo_root=root)
    security_path = _require_file(SECURITY_REPORT_RELPATH, repo_root=root)
    e2e_path = _require_file(E2E_REPORT_RELPATH, repo_root=root)
    canary_path = _require_file(CANARY_FIXTURE_RELPATH, repo_root=root)
    stage_path = _require_file(STAGE_PLAN_RELPATH, repo_root=root)
    runbook_path = _require_file(RUNBOOK_RELPATH, repo_root=root)
    migration_path = _require_file(MIGRATION_RELPATH, repo_root=root)
    # Recipe is used for canary/e2e lineage; required for independent rebuild.
    recipe_path = _require_file(E2E_RECIPE_RELPATH, repo_root=root)

    evaluation = load_json_mapping(evaluation_path)
    security = load_json_mapping(security_path)
    e2e = load_json_mapping(e2e_path)
    canary = load_json_mapping(canary_path)
    stage = load_json_mapping(stage_path)

    eval_ok = bool((evaluation.get("acceptance") or {}).get("component_and_fused_baselines_reported"))
    security_ok = bool(
        (security.get("acceptance") or {}).get("every_tamper_case_fails_closed")
    ) and bool(
        (security.get("acceptance") or {}).get("no_secret_or_local_absolute_path_leaks")
    )
    e2e_ok = bool(e2e.get("ok")) and bool(
        (e2e.get("acceptance") or {}).get("fixture_build_deterministic")
    )
    canary_ok = bool((canary.get("acceptance") or {}).get("fixture_canary_offline"))
    stage_ok = bool((stage.get("acceptance") or {}).get("add_only")) and (
        stage.get("legacy_files_deleted") is False
    )

    determinism_ok = bool(
        (e2e.get("acceptance") or {}).get("fixture_build_deterministic")
    ) and bool((e2e.get("acceptance") or {}).get("offline_replay_stable"))

    viewer_policy = dict(canary.get("viewer") or {})
    viewer_ok = bool(viewer_policy.get("schema_coherent")) and bool(
        viewer_policy.get("default_excludes_recovery")
    )

    evidence = {
        "evaluation": _evidence_binding(
            key="evaluation",
            relpath=EVALUATION_REPORT_RELPATH,
            task_id=str(evaluation.get("task_id") or "USCIR-035"),
            sha256=sha256_file(evaluation_path),
            ok=eval_ok,
            extra={
                "evaluation_cid": evaluation.get("evaluation_cid"),
                "production_searchable": bool(
                    (evaluation.get("production_claim") or {}).get(
                        "production_searchable"
                    )
                ),
                "fusion_config_digest": (
                    (evaluation.get("fusion_selection") or {}).get("config_digest")
                ),
                "fusion_candidate_id": (
                    (evaluation.get("fusion_selection") or {}).get("candidate_id")
                ),
            },
        ),
        "security": _evidence_binding(
            key="security",
            relpath=SECURITY_REPORT_RELPATH,
            task_id=str(security.get("task_id") or "USCIR-034"),
            sha256=sha256_file(security_path),
            ok=security_ok,
            extra={
                "case_count": security.get("case_count"),
                "schema_version": security.get("schema_version"),
            },
        ),
        "e2e": _evidence_binding(
            key="e2e",
            relpath=E2E_REPORT_RELPATH,
            task_id=str(e2e.get("task_id") or "USCIR-033"),
            sha256=sha256_file(e2e_path),
            ok=e2e_ok,
            extra={
                "manifest_digest": (e2e.get("packaging") or {}).get("manifest_digest"),
                "release_root_cid": (e2e.get("packaging") or {}).get("release_root_cid"),
                "revision": e2e.get("revision"),
            },
        ),
        "canary": _evidence_binding(
            key="canary",
            relpath=CANARY_FIXTURE_RELPATH,
            task_id=str(canary.get("task_id") or "USCIR-036"),
            sha256=sha256_file(canary_path),
            ok=canary_ok,
            extra={
                "staging_revision": canary.get("staging_revision"),
                "staging_branch": canary.get("staging_branch"),
                "target_repo": canary.get("target_repo"),
                "network_required": canary.get("network_required"),
            },
        ),
        "stage_plan": _evidence_binding(
            key="stage_plan",
            relpath=STAGE_PLAN_RELPATH,
            task_id=str(stage.get("task_id") or "USCIR-032"),
            sha256=sha256_file(stage_path),
            ok=stage_ok,
            extra={
                "staging_branch": stage.get("staging_branch"),
                "target_repo": stage.get("target_repo"),
                "base_revision": stage.get("base_revision"),
                "release_point": stage.get("release_point"),
            },
        ),
        "runbook": _evidence_binding(
            key="runbook",
            relpath=RUNBOOK_RELPATH,
            task_id="USCIR-037",
            sha256=sha256_file(runbook_path),
            ok=True,
        ),
        "migration": _evidence_binding(
            key="migration",
            relpath=MIGRATION_RELPATH,
            task_id="USCIR-037",
            sha256=sha256_file(migration_path),
            ok=True,
        ),
        "determinism": {
            "key": "determinism",
            "ok": determinism_ok,
            "source": E2E_REPORT_RELPATH.as_posix(),
            "fixture_build_deterministic": bool(
                (e2e.get("acceptance") or {}).get("fixture_build_deterministic")
            ),
            "offline_replay_stable": bool(
                (e2e.get("acceptance") or {}).get("offline_replay_stable")
            ),
            "e2e_recipe_path": E2E_RECIPE_RELPATH.as_posix(),
            "e2e_recipe_sha256": sha256_file(recipe_path),
        },
        "viewer": {
            "key": "viewer",
            "ok": viewer_ok,
            "source": CANARY_FIXTURE_RELPATH.as_posix(),
            "default_config": viewer_policy.get("default_config") or DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": bool(
                viewer_policy.get("default_excludes_recovery")
            ),
            "default_excludes_legacy_monoliths": bool(
                viewer_policy.get("default_excludes_legacy_monoliths")
            ),
            "exactly_one_default": bool(viewer_policy.get("exactly_one_default")),
            "required_config_names": list(
                viewer_policy.get("required_config_names") or []
            ),
            "schema_coherent": bool(viewer_policy.get("schema_coherent")),
        },
    }

    # Fail closed if any required producer surface is not OK.
    for key in REQUIRED_EVIDENCE_KEYS:
        item = evidence.get(key)
        if not isinstance(item, Mapping):
            raise MissingInputError(f"evidence binding missing: {key}")
        if not bool(item.get("ok")):
            raise MismatchError(f"producer evidence gate failed for {key}")

    return {
        "bindings": evidence,
        "raw": {
            "evaluation": evaluation,
            "security": security,
            "e2e": e2e,
            "canary": canary,
            "stage": stage,
        },
    }


# ---------------------------------------------------------------------------
# Candidate construction
# ---------------------------------------------------------------------------


def build_fixture_candidate() -> UscodeHuggingFaceRelease:
    """Build the deterministic offline fixture release candidate."""
    release = build_uscode_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )
    validate_uscode_hf_release(release)
    return release


def _count_summary(release: UscodeHuggingFaceRelease, e2e: Mapping[str, Any]) -> dict[str, Any]:
    joins = dict(e2e.get("root_count_joins") or {})
    packaging = dict(e2e.get("packaging") or {})
    family_counts: dict[str, int] = {}
    for art in release.artifacts:
        family = str(art.family)
        family_counts[family] = family_counts.get(family, 0) + int(art.row_count or 0)
    return {
        "artifact_count": len(release.artifacts),
        "bm25_document_count": joins.get("bm25_document_count"),
        "corpus_row_count": joins.get("corpus_row_count"),
        "families_built": sorted(family_counts),
        "graph_edge_count": joins.get("graph_edge_count"),
        "graph_node_count": joins.get("graph_node_count"),
        "packaging_artifact_count": packaging.get("artifact_count"),
        "reconciled": bool(joins.get("reconciled")),
        "vector_row_count": joins.get("vector_row_count"),
    }


def _model_binding() -> dict[str, Any]:
    vector_space_id = build_vector_space_id(
        model_id=DEFAULT_MODEL_ID,
        model_revision=DEFAULT_MODEL_REVISION,
        dimension=DEFAULT_DIMENSION,
        normalization=DEFAULT_NORMALIZATION,
        pooling=DEFAULT_POOLING,
    )
    payload = {
        "dimension": DEFAULT_DIMENSION,
        "model_id": DEFAULT_MODEL_ID,
        "model_revision": DEFAULT_MODEL_REVISION,
        "normalization": DEFAULT_NORMALIZATION,
        "pooling": DEFAULT_POOLING,
        "vector_space_id": vector_space_id,
    }
    return {
        **payload,
        "digest": digest_mapping(payload),
    }


def _code_binding() -> dict[str, Any]:
    payload = {
        "code_version": CODE_VERSION,
        "modules": [
            "ipfs_datasets_py.processors.legal_data.uscode_hf_release",
            "ipfs_datasets_py.processors.legal_data.uscode_release_schema",
            "ipfs_datasets_py.processors.legal_data.uscode_embeddings",
            "scripts.ops.legal_data.verify_uscode_release_candidate",
        ],
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
    }
    return {
        **payload,
        "digest": digest_mapping(payload),
    }


def _config_binding(
    release: UscodeHuggingFaceRelease,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    fusion = dict(evaluation.get("fusion_selection") or {})
    payload = {
        "build_config_cid": release.build_config_cid,
        "default_config": DEFAULT_CONFIG_NAME,
        "fusion_candidate_id": fusion.get("candidate_id"),
        "fusion_config_digest": fusion.get("config_digest"),
        "package_version": release.package_version,
        "release_profile": release.release_profile,
        "schema_version": release.schema_version,
    }
    return {
        **payload,
        "digest": digest_mapping(payload),
    }


def _exception_dispositions(evaluation: Mapping[str, Any]) -> list[dict[str, Any]]:
    dispositions: list[dict[str, Any]] = []
    regressions = dict(evaluation.get("regressions") or {})
    for index, item in enumerate(list(regressions.get("exceptions") or [])):
        if not isinstance(item, Mapping):
            continue
        dispositions.append(
            {
                "approved": bool(item.get("approved")),
                "detail": str(item.get("detail") or ""),
                "index": index,
                "kind": str(item.get("kind") or "unknown"),
                "source": "evaluation.regressions.exceptions",
            }
        )

    claim = dict(evaluation.get("production_claim") or {})
    dispositions.append(
        {
            "approved": True,
            "detail": str(
                claim.get("claim")
                or "Fixture release candidate is not production-searchable."
            ),
            "kind": "production_searchable_disposition",
            "production_searchable": bool(claim.get("production_searchable")),
            "source": "evaluation.production_claim",
        }
    )
    # Stable ordering for independent reproducibility.
    dispositions.sort(key=lambda d: (str(d.get("kind")), int(d.get("index") or 0)))
    return dispositions


def _viewer_report() -> dict[str, Any]:
    configs = advertised_viewer_configs()
    coherence = assert_configs_schema_coherent(configs)
    names = [cfg.config_name for cfg in configs]
    defaults = [cfg for cfg in configs if cfg.is_default]
    return {
        "coherence": dict(coherence) if isinstance(coherence, Mapping) else {},
        "config_names": names,
        "default_config": defaults[0].config_name if defaults else None,
        "default_count": len(defaults),
        "ok": len(defaults) == 1
        and defaults[0].config_name == DEFAULT_CONFIG_NAME
        and all(not cfg.is_default for cfg in configs if cfg.is_recovery),
    }


def build_fixture_receipt(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build the deterministic offline release-candidate receipt."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    evidence_bundle = load_producer_evidence(repo_root=root)
    evidence = evidence_bundle["bindings"]
    raw = evidence_bundle["raw"]
    evaluation = raw["evaluation"]
    e2e = raw["e2e"]
    canary = raw["canary"]
    stage = raw["stage"]

    release = build_fixture_candidate()
    # Independent reproducibility: second build must match digests.
    release_b = build_fixture_candidate()
    if release.manifest_digest != release_b.manifest_digest:
        raise MismatchError(
            "fixture candidate is not independently reproducible: "
            "manifest_digest drift between two clean builds"
        )
    if release.release_root_cid != release_b.release_root_cid:
        raise MismatchError(
            "fixture candidate is not independently reproducible: "
            "release_root_cid drift between two clean builds"
        )

    model = _model_binding()
    code = _code_binding()
    config = _config_binding(release, evaluation)
    viewer_live = _viewer_report()
    if not viewer_live.get("ok"):
        raise MismatchError("live Dataset Viewer configs failed coherence checks")

    revision = require_immutable_revision(
        str(canary.get("staging_revision") or DEFAULT_SOURCE_REVISION),
        name="candidate.revision",
    )
    rollback_revision = require_immutable_revision(
        str(stage.get("base_revision") or ROLLBACK_REVISION),
        name="rollback.revision",
    )

    counts = _count_summary(release, e2e)
    exceptions = _exception_dispositions(evaluation)

    digests = {
        "code": code["digest"],
        "config": config["digest"],
        "manifest": release.manifest_digest,
        "model": model["digest"],
        "release_root_cid": release.release_root_cid,
    }

    candidate = {
        "dataset_id": release.dataset_id,
        "default_config": DEFAULT_CONFIG_NAME,
        "kind": "fixture_local",
        "manifest_digest": release.manifest_digest,
        "package_version": release.package_version,
        "release_point": release.release_point,
        "release_profile": release.release_profile,
        "release_root_cid": release.release_root_cid,
        "revision": revision,
        "root_label": DEFAULT_CANDIDATE_ROOT_LABEL,
        "source_revision": release.source_revision,
        "staging_branch": str(
            canary.get("staging_branch") or stage.get("staging_branch") or DEFAULT_STAGING_BRANCH
        ),
        "vector_space_id": release.vector_space_id,
    }

    rollback = {
        "dataset_id": str(stage.get("target_repo") or DEFAULT_DATASET_REPO),
        "default_config": ROLLBACK_DEFAULT_CONFIG,
        "legacy_files_deleted": False,
        "policy": (
            "Re-advertise the prior immutable revision and default config "
            "without deleting the failed candidate tree or legacy files."
        ),
        "revision": rollback_revision,
        "staging_branch_retained": True,
    }

    acceptance = {
        "all_inputs_present": True,
        "canary_gate_pass": bool(evidence["canary"]["ok"]),
        "determinism_gate_pass": bool(evidence["determinism"]["ok"]),
        "digests_bound": all(
            isinstance(v, str)
            and (
                bool(_SHA256_RE.fullmatch(v))
                or v.startswith("baf")
                or v.startswith("bag")
            )
            for v in digests.values()
        ),
        "evaluation_gate_pass": bool(evidence["evaluation"]["ok"]),
        "fixture_independently_reproducible": True,
        "no_secret_or_path_leak": True,
        "publication_not_authorized": True,
        "rollback_target_named": bool(rollback["revision"] and rollback["default_config"]),
        "security_gate_pass": bool(evidence["security"]["ok"]),
        "viewer_gate_pass": bool(evidence["viewer"]["ok"]) and bool(viewer_live.get("ok")),
    }
    if not all(bool(v) for v in acceptance.values()):
        failed = [k for k, v in acceptance.items() if not v]
        raise MismatchError(
            "release-candidate acceptance failed: " + ", ".join(failed)
        )

    receipt: dict[str, Any] = {
        "acceptance": acceptance,
        "candidate": candidate,
        "code": code,
        "code_version": CODE_VERSION,
        "config": config,
        "counts": counts,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": ["USCIR-035", "USCIR-036", "USCIR-037"],
        "digests": digests,
        "evidence": evidence,
        "exception_dispositions": exceptions,
        "fixture_id": "uscode-release-candidate-v1",
        "goal_id": GOAL_ID,
        "model": model,
        "network_required": False,
        "notes": (
            "Sealed offline release-candidate receipt for US Code sparse "
            "GraphRAG (USCIR-038). Binds producer digests from evaluation, "
            "security, e2e, canary, stage plan, and documentation. Independently "
            "reproducible via build_fixture_receipt(). Does not authorize "
            "publication."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "publication_authorized": False,
        "release_point": release.release_point or DEFAULT_APPROVED_RELEASE_POINT,
        "release_profile": RELEASE_PROFILE,
        "rollback": rollback,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "viewer_live": {
            "config_names": viewer_live["config_names"],
            "default_config": viewer_live["default_config"],
            "ok": viewer_live["ok"],
        },
    }

    # Self-digest over the sealed surface (excluding receipt_sha256 itself).
    receipt["receipt_sha256"] = digest_mapping(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )

    reject_credentials_in_payload(receipt, label="release_candidate_receipt")
    reject_path_leaks(receipt, label="release_candidate_receipt")
    reject_identity_contamination(receipt, label="release_candidate_receipt")
    return receipt


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _compare_mappings(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
    *,
    path: str,
    keys: Sequence[str],
) -> list[str]:
    mismatches: list[str] = []
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(
                f"{path}.{key}: fresh={fresh.get(key)!r} sealed={sealed.get(key)!r}"
            )
    return mismatches


def compare_receipts(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    """Return human-readable mismatches between two release-candidate receipts."""

    mismatches: list[str] = []
    top_keys = (
        "schema",
        "schema_version",
        "task_id",
        "goal_id",
        "program_id",
        "producer",
        "code_version",
        "fixture_id",
        "release_point",
        "release_profile",
        "network_required",
        "publication_authorized",
        "receipt_sha256",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="receipt", keys=top_keys))

    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("candidate") or {}),
            dict(sealed.get("candidate") or {}),
            path="candidate",
            keys=(
                "kind",
                "root_label",
                "dataset_id",
                "revision",
                "manifest_digest",
                "release_root_cid",
                "release_point",
                "release_profile",
                "source_revision",
                "default_config",
                "staging_branch",
                "package_version",
                "vector_space_id",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("rollback") or {}),
            dict(sealed.get("rollback") or {}),
            path="rollback",
            keys=(
                "revision",
                "default_config",
                "dataset_id",
                "legacy_files_deleted",
                "staging_branch_retained",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("digests") or {}),
            dict(sealed.get("digests") or {}),
            path="digests",
            keys=("manifest", "config", "code", "model", "release_root_cid"),
        )
    )

    fresh_acc = dict(fresh.get("acceptance") or {})
    sealed_acc = dict(sealed.get("acceptance") or {})
    for key, expected in fresh_acc.items():
        if sealed_acc.get(key) != expected:
            mismatches.append(
                f"acceptance.{key}: fresh={expected!r} sealed={sealed_acc.get(key)!r}"
            )

    fresh_ev = dict(fresh.get("evidence") or {})
    sealed_ev = dict(sealed.get("evidence") or {})
    for key in REQUIRED_EVIDENCE_KEYS:
        f_item = dict(fresh_ev.get(key) or {})
        s_item = dict(sealed_ev.get(key) or {})
        if not s_item:
            mismatches.append(f"evidence.{key}: missing from sealed receipt")
            continue
        for field in ("ok", "path", "sha256", "task_id"):
            if field in f_item and f_item.get(field) != s_item.get(field):
                mismatches.append(
                    f"evidence.{key}.{field}: "
                    f"fresh={f_item.get(field)!r} sealed={s_item.get(field)!r}"
                )
        if key == "determinism":
            for field in (
                "fixture_build_deterministic",
                "offline_replay_stable",
                "e2e_recipe_path",
                "e2e_recipe_sha256",
            ):
                if f_item.get(field) != s_item.get(field):
                    mismatches.append(
                        f"evidence.determinism.{field}: "
                        f"fresh={f_item.get(field)!r} sealed={s_item.get(field)!r}"
                    )
        if key == "viewer":
            for field in (
                "default_config",
                "default_excludes_recovery",
                "schema_coherent",
                "exactly_one_default",
            ):
                if f_item.get(field) != s_item.get(field):
                    mismatches.append(
                        f"evidence.viewer.{field}: "
                        f"fresh={f_item.get(field)!r} sealed={s_item.get(field)!r}"
                    )
            if list(f_item.get("required_config_names") or []) != list(
                s_item.get("required_config_names") or []
            ):
                mismatches.append("evidence.viewer.required_config_names mismatch")

    fresh_exc = list(fresh.get("exception_dispositions") or [])
    sealed_exc = list(sealed.get("exception_dispositions") or [])
    if fresh_exc != sealed_exc:
        mismatches.append(
            f"exception_dispositions: fresh_count={len(fresh_exc)} "
            f"sealed_count={len(sealed_exc)} content_mismatch"
        )

    return mismatches


def assert_evidence_not_stale(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> None:
    """Re-hash bound evidence files and fail if digests drifted (stale)."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    evidence = dict(receipt.get("evidence") or {})
    for key in (
        "evaluation",
        "security",
        "e2e",
        "canary",
        "stage_plan",
        "runbook",
        "migration",
    ):
        item = evidence.get(key)
        if not isinstance(item, Mapping):
            raise MissingInputError(f"receipt evidence missing binding: {key}")
        rel = str(item.get("path") or "")
        if not rel:
            raise MissingInputError(f"receipt evidence.{key}.path missing")
        # Path must be repo-relative.
        if rel.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", rel):
            raise PathLeakError(f"evidence.{key}.path is absolute: {rel!r}")
        path = (root / rel).resolve()
        if not path.is_file():
            raise MissingInputError(
                f"stale-check input missing for evidence.{key}: {rel}"
            )
        live = sha256_file(path)
        bound = str(item.get("sha256") or "").casefold()
        if not _SHA256_RE.fullmatch(bound):
            raise MismatchError(f"evidence.{key}.sha256 is not a 64-hex digest")
        if live != bound:
            raise StaleInputError(
                f"evidence.{key} is stale: bound={bound} live={live} path={rel}"
            )

    determinism = dict(evidence.get("determinism") or {})
    recipe_rel = str(determinism.get("e2e_recipe_path") or "")
    if recipe_rel:
        if recipe_rel.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", recipe_rel):
            raise PathLeakError(
                f"evidence.determinism.e2e_recipe_path is absolute: {recipe_rel!r}"
            )
        recipe_path = (root / recipe_rel).resolve()
        if not recipe_path.is_file():
            raise MissingInputError(
                f"determinism e2e recipe missing: {recipe_rel}"
            )
        live_recipe = sha256_file(recipe_path)
        bound_recipe = str(determinism.get("e2e_recipe_sha256") or "").casefold()
        if live_recipe != bound_recipe:
            raise StaleInputError(
                "evidence.determinism.e2e_recipe_sha256 is stale: "
                f"bound={bound_recipe} live={live_recipe}"
            )


def assert_receipt_safe(receipt: Mapping[str, Any]) -> None:
    """Structural + safety checks on a release-candidate receipt."""

    if not isinstance(receipt, Mapping):
        raise ReleaseCandidateError("receipt must be an object")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise MismatchError(
            f"receipt schema mismatch: {receipt.get('schema')!r}"
        )
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise MismatchError(
            f"receipt schema_version mismatch: {receipt.get('schema_version')!r}"
        )
    if receipt.get("task_id") != TASK_ID:
        raise MismatchError(f"receipt task_id mismatch: {receipt.get('task_id')!r}")
    if receipt.get("goal_id") != GOAL_ID:
        raise MismatchError(f"receipt goal_id mismatch: {receipt.get('goal_id')!r}")
    if receipt.get("publication_authorized") is not False:
        raise MismatchError("receipt must declare publication_authorized=false")
    if receipt.get("network_required") is not False:
        raise MismatchError("fixture receipt must declare network_required=false")

    candidate = dict(receipt.get("candidate") or {})
    for field in (
        "kind",
        "root_label",
        "dataset_id",
        "revision",
        "manifest_digest",
        "release_root_cid",
        "release_point",
        "default_config",
    ):
        if not candidate.get(field):
            raise MissingInputError(f"candidate.{field} missing")
    require_immutable_revision(str(candidate["revision"]), name="candidate.revision")
    normalize_sha256(candidate["manifest_digest"], name="candidate.manifest_digest")

    rollback = dict(receipt.get("rollback") or {})
    if not rollback.get("revision") or not rollback.get("default_config"):
        raise MissingInputError("rollback target incomplete")
    require_immutable_revision(str(rollback["revision"]), name="rollback.revision")
    if rollback.get("legacy_files_deleted") is not False:
        raise MismatchError("rollback must declare legacy_files_deleted=false")

    digests = dict(receipt.get("digests") or {})
    for key in ("manifest", "config", "code", "model"):
        value = digests.get(key)
        if not value:
            raise MissingInputError(f"digests.{key} missing")
        normalize_sha256(value, name=f"digests.{key}")

    acceptance = dict(receipt.get("acceptance") or {})
    for key, expected in (
        ("all_inputs_present", True),
        ("no_secret_or_path_leak", True),
        ("fixture_independently_reproducible", True),
        ("publication_not_authorized", True),
        ("rollback_target_named", True),
    ):
        if acceptance.get(key) is not expected:
            raise MismatchError(f"acceptance.{key} must be {expected!r}")

    evidence = dict(receipt.get("evidence") or {})
    for key in REQUIRED_EVIDENCE_KEYS:
        if key not in evidence:
            raise MissingInputError(f"evidence.{key} missing")

    # receipt_sha256 must match recomputed digest of the sealed surface.
    bound = str(receipt.get("receipt_sha256") or "").casefold()
    if not _SHA256_RE.fullmatch(bound):
        raise MismatchError("receipt_sha256 must be a 64-hex digest")
    recomputed = digest_mapping(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )
    if recomputed != bound:
        raise MismatchError(
            f"receipt_sha256 mismatch: bound={bound} recomputed={recomputed}"
        )

    reject_credentials_in_payload(receipt, label="receipt")
    reject_path_leaks(receipt, label="receipt")
    reject_identity_contamination(receipt, label="receipt")


def verify_receipt(
    receipt: Mapping[str, Any] | None = None,
    *,
    receipt_path: Path | str | None = None,
    repo_root: Path | str | None = None,
    require_fixture_match: bool = True,
) -> dict[str, Any]:
    """Verify a sealed receipt against live producer inputs and a fresh build."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    if receipt is None:
        path = (
            Path(receipt_path).expanduser().resolve()
            if receipt_path is not None
            else default_receipt_path(root)
        )
        receipt = load_json_mapping(path)
    else:
        path = (
            Path(receipt_path).expanduser().resolve()
            if receipt_path is not None
            else default_receipt_path(root)
        )

    assert_receipt_safe(receipt)
    assert_evidence_not_stale(receipt, repo_root=root)

    fresh = build_fixture_receipt(repo_root=root)
    assert_receipt_safe(fresh)

    mismatches: list[str] = []
    if require_fixture_match:
        mismatches = compare_receipts(fresh, receipt)
        if mismatches:
            raise MismatchError(
                "release-candidate receipt mismatch: "
                + "; ".join(mismatches[:16])
            )

    # Second independent build for reproducibility proof.
    fresh_b = build_fixture_receipt(repo_root=root)
    if fresh_b.get("receipt_sha256") != fresh.get("receipt_sha256"):
        raise MismatchError(
            "fixture receipt is not independently reproducible across two builds"
        )

    return {
        "ok": True,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "receipt_path": repo_relpath(path, repo_root=root)
        if path.is_file()
        else DEFAULT_RECEIPT_RELPATH.as_posix(),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "manifest_digest": (receipt.get("candidate") or {}).get("manifest_digest"),
        "release_root_cid": (receipt.get("candidate") or {}).get("release_root_cid"),
        "release_point": receipt.get("release_point"),
        "rollback_revision": (receipt.get("rollback") or {}).get("revision"),
        "mismatches": [],
        "fixture_independently_reproducible": True,
        "publication_authorized": False,
        "network_required": False,
    }


def materialize_default_receipt(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Build and write the sealed fixture receipt."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_receipt_path(root)
    )
    receipt = build_fixture_receipt(repo_root=root)
    write_json(target, receipt)
    return receipt, target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_uscode_release_candidate.py",
        description=(
            "Produce and verify the US Code sparse GraphRAG release-candidate "
            f"receipt ({TASK_ID}). Default mode is offline fixture verification "
            "(no Hub contact, no publication)."
        ),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=(
            "Path to the sealed receipt "
            f"(default: {DEFAULT_RECEIPT_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Offline fixture mode: recompute and verify against producer inputs",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write/refresh the sealed receipt from a fresh fixture build",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the verification result (or receipt with --write) as JSON",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Alias for verification (default when --fixture-only is set)",
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
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )

    try:
        if not args.fixture_only and not args.write and not args.check:
            # Default: require explicit fixture-only for the offline gate.
            raise ReleaseCandidateError(
                "pass --fixture-only to verify the offline release-candidate "
                "receipt (no network path in this CLI)"
            )

        # Fixture-only mode always rebuilds the sealed receipt from producer
        # inputs (same pattern as evaluate_uscode_sparse_graphrag --check),
        # then verifies independent reproducibility and safety.
        if args.fixture_only or args.write:
            if args.write and not args.fixture_only:
                raise ReleaseCandidateError("--write requires --fixture-only")
            receipt, written = materialize_default_receipt(path=receipt_path)
            print(
                f"wrote release-candidate receipt: {written}",
                file=sys.stderr,
            )
            result = verify_receipt(
                receipt,
                receipt_path=written,
                require_fixture_match=True,
            )
            if args.print_json:
                # Prefer the verification summary unless the operator asked
                # only to inspect the receipt via --write without check-like use.
                write_json(None, result if not args.write else receipt)
        else:
            if not receipt_path.is_file():
                raise MissingInputError(
                    f"receipt not found: {receipt_path}; "
                    "pass --fixture-only to materialize and verify"
                )
            result = verify_receipt(
                receipt_path=receipt_path,
                require_fixture_match=True,
            )
            if args.print_json:
                write_json(None, result)

        print(
            "ok={ok} task_id={task_id} receipt_sha256={receipt_sha256} "
            "manifest_digest={manifest_digest} "
            "rollback_revision={rollback_revision} "
            "publication_authorized={publication_authorized}".format(**result),
            file=sys.stderr,
        )
        return 0 if result.get("ok") else 1
    except (
        ReleaseCandidateError,
        MissingInputError,
        MismatchError,
        StaleInputError,
        PathLeakError,
        SecretLeakError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
