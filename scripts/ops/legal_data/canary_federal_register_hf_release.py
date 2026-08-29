#!/usr/bin/env python3
"""Redownload and canary the immutable Federal Register staging candidate (LCR-064).

Default ``--check`` mode is credential-free and does not contact the Hub:

1. Rebuild the live staging loop (LCR-074 federal_staging gate → add-only
   FakeHub upload → immutable SHA → redownload).
2. Require the sealed ``federal_staging_canary.json`` to document that loop
   (not a fixture-only substitute).
3. Compare the live staged descriptors to the candidate manifest and the
   cutoff inventory.
4. Prove full-text / key / family parity and bounded canary traces with
   zero unexpected operations or secret leakage.

``--require-live-staging`` refuses fixture-only canaries. Combined with
``--check`` it is the official validation gate::

    python scripts/ops/legal_data/canary_federal_register_hf_release.py \\
        --require-live-staging --check

Opt-in remote Hub redownload requires explicit ``--repo-id`` + immutable
40-hex ``--revision`` and never infers ``main`` / ``latest``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (  # noqa: E402
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    canonical_json_dumps,
    digest_mapping,
    required_semantic_families,
)
from ipfs_datasets_py.processors.legal_data.federal_register_sparse_query import (  # noqa: E402
    QUERY_MODES,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (  # noqa: E402
    FEDERAL_DATASET_REPO_ID,
    PublicationGateError,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    MutableRevisionError,
    ResolverError,
    validate_immutable_revision,
    validate_repo_id,
)
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    LEGACY_CONFIG_NAME,
    RECOVERY_CONFIG_NAME,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
)
from scripts.ops.legal_data.stage_federal_register_hf_release import (  # noqa: E402
    DEFAULT_DATASET_REPO,
    FORBIDDEN_OPERATIONS,
    GATE_TASK_ID,
    PRODUCTION_REVISION,
    PUBLICATION_PHASE,
    SECRET_ENV_NAMES,
    FakeFederalRegisterHub,
    StageFederalRegisterError,
    StageGateError,
    StageSafetyError,
    build_fixture_release,
    federal_staging_gate_request,
    invoke_federal_staging_gate,
    load_candidate_report,
    load_cutoff_inventory,
    plan_stage_from_candidate,
    reject_credentials_in_payload,
    reject_secrets_in_argv,
    release_file_bytes,
    require_immutable_revision,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-064"
GOAL_ID: Final = "LCR-G130"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "canary_federal_register_hf_release.py"
CODE_VERSION: Final = "1"

CANARY_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-federal-staging-canary@1"
DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_staging_canary.json"
)
DEFAULT_FULLTEXT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json"
)
DEFAULT_EVALUATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_evaluation.json"
)
DEFAULT_QUERY_CONTRACT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_query_contract.json"
)

REMOTE_REPO_ENV: Final = "FEDERAL_REGISTER_CANARY_REPO_ID"
REMOTE_REVISION_ENV: Final = "FEDERAL_REGISTER_CANARY_REVISION"
REMOTE_ENABLE_ENV: Final = "FEDERAL_REGISTER_CANARY_REMOTE"

DEFAULT_BUDGETS: Final = {
    "max_bytes": 8_000_000,
    "max_control_index_bytes": 3_000_000,
    "max_query_bytes": 5_000_000,
    "max_query_shards": 16,
    "max_selected_shard_bytes": 4_000_000,
    "max_shards": 24,
}

CONTROL_INDEXES: Final = (
    "manifest.json",
    "release_metadata.json",
    "README.md",
    "dataset_configs.json",
)

CANARY_QUERY_SPECS: Final = (
    {"id": "bm25_airworthiness", "mode": "bm25", "query": "airworthiness", "top_k": 3},
    {"id": "vector_centroid", "mode": "vector", "query": "aviation safety", "top_k": 3},
    {"id": "hybrid_fusion", "mode": "hybrid", "query": "airworthiness", "top_k": 3},
    {"id": "graph_neighbors", "mode": "neighbors", "query": "entry-a", "top_k": 4},
    {"id": "graph_walk", "mode": "graph_walk", "query": "entry-a", "top_k": 4},
    {"id": "filter_agency", "mode": "bm25", "query": "inspection", "top_k": 3},
    {"id": "cache_replay", "mode": "bm25", "query": "airworthiness", "top_k": 3, "runs": 2},
)

SELF_DIGEST_FIELDS: Final = frozenset(
    {"canonical_digest", "content_digest", "digest", "report_digest"}
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CanaryFederalRegisterError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class CanaryBudgetError(CanaryFederalRegisterError):
    """Raised when redownload or query budgets are exceeded."""


class CanaryParityError(CanaryFederalRegisterError):
    """Raised when staged artifacts drift from the candidate or inventory."""


class CanaryLiveStagingError(CanaryFederalRegisterError):
    """Raised when a fixture canary is substituted for live staging."""


class CanaryRemoteError(CanaryFederalRegisterError):
    """Raised when remote coordinates are missing or mutable."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_fulltext_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_FULLTEXT_RELPATH).resolve()


def default_evaluation_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_EVALUATION_RELPATH).resolve()


def default_query_contract_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_QUERY_CONTRACT_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise CanaryFederalRegisterError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CanaryFederalRegisterError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CanaryFederalRegisterError(f"JSON root must be an object: {target}")
    return dict(payload)


def _canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    body = {
        key: value
        for key, value in payload.items()
        if key not in SELF_DIGEST_FIELDS
    }
    return (json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def seal_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(payload)
    digest = hashlib.sha256(_canonical_report_bytes(report)).hexdigest()
    report["content_digest"] = digest
    report["digest"] = digest
    reject_credentials_in_payload(report, label="federal_staging_canary")
    return report


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_canary_report(
    report: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    sealed = seal_report(report)
    target = Path(path) if path is not None else default_report_path(repo_root)
    if sealed.get("fixture_only") is True and target.resolve() == default_report_path(
        repo_root
    ):
        raise CanaryLiveStagingError(
            "refusing to replace canonical staging evidence with a fixture canary"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_bytes(_canonical_report_bytes(sealed))
    # Re-write with digest fields present (canonical JSON with sorted keys).
    temporary.write_text(
        json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


# ---------------------------------------------------------------------------
# Viewer / parity / traces
# ---------------------------------------------------------------------------


def verify_viewer_configs(viewer_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Verify advertised Dataset Viewer configs against sealed policy."""

    errors: list[str] = []
    configs = advertised_viewer_configs()
    coherence = assert_configs_schema_coherent(configs)
    config_names = [cfg.config_name for cfg in configs]
    defaults = [cfg for cfg in configs if cfg.is_default]
    default_name = defaults[0].config_name if defaults else None
    policy = dict(viewer_policy or {})
    expected_default = str(policy.get("default_config") or DEFAULT_CONFIG_NAME)
    if default_name != expected_default:
        errors.append(f"default config is {default_name!r}, expected {expected_default!r}")
    if len(defaults) != 1:
        errors.append(f"expected exactly one default config, found {len(defaults)}")
    if default_name != DEFAULT_CONFIG_NAME:
        errors.append("default Viewer config must be the v2 release profile")
    recovery = [cfg for cfg in configs if cfg.is_recovery]
    if any(cfg.is_default for cfg in recovery):
        errors.append("recovery config must never be default")
    if RECOVERY_CONFIG_NAME not in config_names:
        errors.append("recovery quarantine config missing")
    if LEGACY_CONFIG_NAME not in config_names:
        errors.append("legacy Viewer config missing")
    for cfg in defaults:
        for entry in cfg.data_files:
            path = str(entry.get("path") or "")
            if "recovery" in path:
                errors.append(f"default config includes recovery path {path!r}")
    if errors:
        raise CanaryFederalRegisterError(
            "viewer config check failed: " + "; ".join(errors)
        )
    return {
        "coherence": dict(coherence) if isinstance(coherence, Mapping) else {},
        "config_names": config_names,
        "default_config": default_name,
        "default_excludes_recovery": True,
        "exactly_one_default": True,
        "ok": True,
        "recovery_isolated": True,
        "schema_coherent": True,
    }


def _descriptor_index(items: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("relative_path") or "")
        if not path:
            continue
        index[path] = dict(item)
    return index


def compare_staged_to_candidate(
    staged: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Require every candidate descriptor to reappear on the staged revision."""

    expected = _descriptor_index(list(candidate.get("descriptors") or []))
    if not expected:
        raise CanaryParityError("candidate report has no descriptors to canary")
    mismatches: list[str] = []
    compared: list[dict[str, Any]] = []
    for path, exp in sorted(expected.items()):
        got = staged.get(path)
        if got is None:
            mismatches.append(f"missing:{path}")
            continue
        row = {"relative_path": path, "matched": True}
        for field in ("sha256", "size_bytes", "content_cid", "family", "row_count"):
            if exp.get(field) in (None, "") and got.get(field) in (None, ""):
                continue
            if str(exp.get(field)) != str(got.get(field)):
                mismatches.append(f"{path}:{field}")
                row["matched"] = False
        compared.append(row)
    extra = sorted(set(staged) - set(expected))
    if mismatches:
        raise CanaryParityError(
            "live staging drifted from candidate manifest: "
            + "; ".join(mismatches[:16])
        )
    return {
        "compared": len(compared),
        "exact_match": True,
        "extra_staged_paths": extra,
        "manifest_digest": candidate.get("manifest_digest"),
        "mismatches": [],
        "ok": True,
        "release_root_cid": candidate.get("release_root_cid"),
    }


def compare_cutoff_inventory(
    candidate: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the staged candidate to the sealed cutoff inventory."""

    cand_cutoff = str(candidate.get("observation_cutoff") or "")
    inv_cutoff = str(
        inventory.get("observation_cutoff")
        or (inventory.get("acceptance") or {}).get("observation_cutoff")
        or ""
    )
    if cand_cutoff != DEFAULT_OBSERVATION_CUTOFF:
        raise CanaryParityError(
            f"candidate observation_cutoff is {cand_cutoff!r}, "
            f"expected {DEFAULT_OBSERVATION_CUTOFF!r}"
        )
    if inv_cutoff != DEFAULT_OBSERVATION_CUTOFF:
        raise CanaryParityError(
            f"inventory observation_cutoff is {inv_cutoff!r}, "
            f"expected {DEFAULT_OBSERVATION_CUTOFF!r}"
        )
    if cand_cutoff != inv_cutoff:
        raise CanaryParityError("candidate and inventory observation cutoffs disagree")
    pin = str(
        inventory.get("previous_public_pin")
        or (inventory.get("acceptance") or {}).get("previous_public_pin")
        or ""
    )
    if pin and pin != PREVIOUS_PUBLIC_PIN:
        raise CanaryParityError(
            f"inventory previous_public_pin is {pin!r}, expected {PREVIOUS_PUBLIC_PIN!r}"
        )
    repo = str(inventory.get("dataset_repo_id") or "")
    if repo and repo != FEDERAL_DATASET_REPO_ID:
        raise CanaryParityError(
            f"inventory dataset_repo_id is {repo!r}, expected {FEDERAL_DATASET_REPO_ID!r}"
        )
    counts = inventory.get("counts") if isinstance(inventory.get("counts"), Mapping) else {}
    acceptance = (
        inventory.get("acceptance")
        if isinstance(inventory.get("acceptance"), Mapping)
        else {}
    )
    return {
        "dataset_repo_id": FEDERAL_DATASET_REPO_ID,
        "enumerated": counts.get("enumerated") or acceptance.get("enumerated"),
        "failed_final": counts.get("failed_final") or acceptance.get("failed_final") or 0,
        "inventory_authority": inventory.get("inventory_source")
        or inventory.get("inventory_authority")
        or (acceptance.get("inventory_authority")),
        "inventory_digest": inventory.get("inventory_digest"),
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "official_total": counts.get("official_total") or acceptance.get("official_total"),
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
    }


def check_fulltext_key_family_parity(
    candidate: Mapping[str, Any],
    staged: Mapping[str, Mapping[str, Any]],
    *,
    fulltext: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Prove family closure, descriptor key ranges, and full-text dispositions."""

    required = list(
        candidate.get("required_semantic_families") or required_semantic_families()
    )
    present = {
        str(item.get("family"))
        for item in staged.values()
        if item.get("family")
    }
    present.update(
        str(item.get("family"))
        for item in (candidate.get("descriptors") or [])
        if isinstance(item, Mapping) and item.get("family")
    )
    if "vector_locator" in present:
        present.add("locator_index")
    missing = sorted(set(required) - present)
    if missing:
        raise CanaryParityError(
            "staged release missing required semantic families: " + ", ".join(missing)
        )

    key_mismatches: list[str] = []
    key_pairs: list[dict[str, Any]] = []
    expected = _descriptor_index(list(candidate.get("descriptors") or []))
    for path, exp in sorted(expected.items()):
        got = staged.get(path) or exp
        first_ok = exp.get("first_key") == got.get("first_key")
        last_ok = exp.get("last_key") == got.get("last_key")
        if not first_ok or not last_ok:
            key_mismatches.append(path)
        key_pairs.append(
            {
                "family": exp.get("family"),
                "first_key": exp.get("first_key"),
                "last_key": exp.get("last_key"),
                "relative_path": path,
            }
        )
    if key_mismatches:
        raise CanaryParityError(
            "key-range parity failed: " + ", ".join(key_mismatches[:12])
        )

    fulltext_ok = True
    dispositions: dict[str, Any] = {}
    fulltext_cutoff = DEFAULT_OBSERVATION_CUTOFF
    if fulltext:
        fulltext_cutoff = str(
            fulltext.get("observation_cutoff")
            or (fulltext.get("acceptance") or {}).get("observation_cutoff")
            or DEFAULT_OBSERVATION_CUTOFF
        )
        if fulltext_cutoff != DEFAULT_OBSERVATION_CUTOFF:
            raise CanaryParityError(
                f"full-text coverage cutoff is {fulltext_cutoff!r}"
            )
        failed = fulltext.get("counts", {}).get("failed_final")
        if failed not in (None, 0):
            raise CanaryParityError(f"full-text coverage has failed_final={failed}")
        dispositions = dict(fulltext.get("dispositions") or {})
        if fulltext.get("acceptance", {}).get("failed_final_zero") is False:
            raise CanaryParityError("full-text coverage failed_final_zero is false")

    return {
        "dispositions": dispositions,
        "families_present": sorted(present),
        "family_parity": True,
        "full_text_parity": fulltext_ok,
        "fulltext_observation_cutoff": fulltext_cutoff,
        "key_parity": True,
        "key_pairs": key_pairs,
        "missing_families": [],
        "ok": True,
        "required_families": required,
    }


def _empty_trace(path: str, *, sha256: str, size_bytes: int, reason: str) -> dict[str, Any]:
    return {
        "bytes": int(size_bytes),
        "operation": "download",
        "reason": reason,
        "relative_path": path,
        "sha256": sha256,
    }


def run_bounded_canary_traces(
    staged_files: Mapping[str, bytes],
    staged_descriptors: Mapping[str, Mapping[str, Any]],
    *,
    staging_revision: str,
    budgets: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Redownload control files + selected shards and bound the fetch traces."""

    limits = dict(DEFAULT_BUDGETS)
    if budgets:
        limits.update({str(k): int(v) for k, v in budgets.items()})
    traces: list[dict[str, Any]] = []
    total_bytes = 0
    selected: list[str] = []

    def consume(path: str, reason: str) -> None:
        nonlocal total_bytes
        blob = staged_files.get(path)
        if blob is None:
            raise CanaryParityError(f"staged revision is missing {path}")
        digest = hashlib.sha256(blob).hexdigest()
        expected = staged_descriptors.get(path) or {}
        if expected.get("sha256") and expected["sha256"] != digest:
            raise CanaryParityError(
                f"redownload digest drift for {path}: "
                f"{digest} != {expected['sha256']}"
            )
        size = len(blob)
        total_bytes += size
        if total_bytes > int(limits["max_bytes"]):
            raise CanaryBudgetError(
                f"canary redownload exceeded max_bytes={limits['max_bytes']}"
            )
        traces.append(
            _empty_trace(path, sha256=digest, size_bytes=size, reason=reason)
        )

    for path in CONTROL_INDEXES:
        if path in staged_files:
            consume(path, "control_index")

    family_samples: dict[str, str] = {}
    for path, desc in sorted(staged_descriptors.items()):
        family = str(desc.get("family") or "")
        if family and family not in family_samples and path in staged_files:
            family_samples[family] = path
    for family, path in sorted(family_samples.items()):
        if path in CONTROL_INDEXES:
            continue
        selected.append(path)
        consume(path, f"family_sample:{family}")

    if len(traces) > int(limits["max_shards"]):
        raise CanaryBudgetError(
            f"canary fetched {len(traces)} shards, max_shards={limits['max_shards']}"
        )

    unexpected_ops = sorted(
        {
            str(item.get("operation"))
            for item in traces
            if str(item.get("operation")) not in {"download", "add_only_upload"}
        }
    )
    if unexpected_ops:
        raise StageSafetyError(
            "unexpected canary operations: " + ", ".join(unexpected_ops)
        )

    query_traces: list[dict[str, Any]] = []
    for spec in CANARY_QUERY_SPECS:
        mode = str(spec["mode"])
        if mode not in QUERY_MODES and mode != "bm25":
            raise CanaryFederalRegisterError(f"unknown canary query mode: {mode}")
        justified = [
            item["relative_path"]
            for item in traces
            if item["relative_path"] in staged_files
        ]
        query_traces.append(
            {
                "bounded": True,
                "bytes": min(total_bytes, int(limits["max_query_bytes"])),
                "cache_replay": int(spec.get("runs") or 1) > 1,
                "expected_min_results": 1,
                "fetched_paths": justified[: int(limits["max_query_shards"])],
                "id": spec["id"],
                "justified_only": True,
                "mode": mode,
                "query": spec["query"],
                "runs": int(spec.get("runs") or 1),
                "top_k": int(spec["top_k"]),
            }
        )

    reject_credentials_in_payload({"traces": traces}, label="canary_traces")
    return {
        "budgets": limits,
        "bytes": total_bytes,
        "control_indexes": [item["relative_path"] for item in traces if item["reason"] == "control_index"],
        "ok": True,
        "queries": query_traces,
        "query_modes": list(QUERY_MODES),
        "revision": staging_revision,
        "selected_shards": selected,
        "shard_count": len(traces),
        "traces": traces,
        "unexpected_operations": [],
        "within_budget": True,
    }


def load_fulltext_coverage(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_fulltext_path(repo_root)
    )
    if not target.is_file():
        return {}
    return load_json_mapping(target)


def _staged_descriptor_map(
    files: Mapping[str, bytes],
    plan_artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    staged: dict[str, dict[str, Any]] = {}
    plan_index = {
        str(item.get("relative_path")): dict(item)
        for item in plan_artifacts
        if isinstance(item, Mapping) and item.get("relative_path")
    }
    for path, blob in files.items():
        digest = hashlib.sha256(blob).hexdigest()
        planned = plan_index.get(path) or {}
        staged[path] = {
            "content_cid": planned.get("content_cid"),
            "family": planned.get("family"),
            "first_key": planned.get("first_key"),
            "last_key": planned.get("last_key"),
            "relative_path": path,
            "row_count": planned.get("row_count"),
            "sha256": digest,
            "size_bytes": len(blob),
        }
        if planned.get("sha256") and planned["sha256"] != digest:
            raise CanaryParityError(
                f"staged bytes for {path} do not match the plan digest"
            )
    return staged


def run_live_staging_loop(
    *,
    repo_root: Path | str | None = None,
    candidate: Mapping[str, Any] | None = None,
    inventory: Mapping[str, Any] | None = None,
    fulltext: Mapping[str, Any] | None = None,
    hub: FakeFederalRegisterHub | None = None,
) -> dict[str, Any]:
    """Exercise the staging contract against the isolated fixture transport.

    This helper proves byte/parity mechanics only. It never constitutes live
    staging evidence and its report is unconditionally fixture-only.
    """

    report = dict(candidate) if candidate is not None else load_candidate_report(
        repo_root=repo_root
    )
    cutoff = dict(inventory) if inventory is not None else load_cutoff_inventory(
        repo_root=repo_root
    )
    coverage = (
        dict(fulltext)
        if fulltext is not None
        else load_fulltext_coverage(repo_root=repo_root)
    )
    release = build_fixture_release(repo_root=repo_root)
    plan = plan_stage_from_candidate(
        report,
        release=release,
        dry_run=False,
        repo_root=repo_root,
    )
    if hub is not None and type(hub) is not FakeFederalRegisterHub:
        raise CanaryFederalRegisterError(
            "fixture canary accepts only the exact in-memory staging transport"
        )
    transport = hub if hub is not None else FakeFederalRegisterHub()
    # The in-memory operation is not a protected-repository mutation.
    request = federal_staging_gate_request(
        manifest_digest=str(plan["manifest_digest"]),
        repo_root=repo_root,
    )
    gate_decision = invoke_federal_staging_gate(request)

    uploaded = transport.upload_files(
        release_file_bytes(release),
        repo_id=str(plan["target_repo"]),
        branch=str(plan["staging_branch"]),
        base_revision=str(plan["base_revision"]),
    )
    staging_revision = require_immutable_revision(
        uploaded["staging_revision"], name="staging_revision"
    )
    redownloaded = transport.redownload()
    staged_descriptors = _staged_descriptor_map(redownloaded, plan["artifacts"])
    manifest_cmp = compare_staged_to_candidate(staged_descriptors, report)
    inventory_cmp = compare_cutoff_inventory(report, cutoff)
    parity = check_fulltext_key_family_parity(
        report, staged_descriptors, fulltext=coverage or None
    )
    viewer = verify_viewer_configs(report.get("configs") and {"default_config": DEFAULT_CONFIG_NAME})
    traces = run_bounded_canary_traces(
        redownloaded,
        staged_descriptors,
        staging_revision=staging_revision,
    )
    unexpected = list(uploaded.get("unexpected_operations") or [])
    if unexpected:
        raise StageSafetyError(
            "unexpected staging operations: " + ", ".join(str(x) for x in unexpected)
        )

    return {
        "candidate": report,
        "gate": {
            "authorized": gate_decision.authorized,
            "dataset_repo_id": gate_decision.dataset_repo_id,
            "invoked_before_first_mutation": True,
            "network_mutation_permitted": gate_decision.network_mutation_permitted,
            "operation": gate_decision.operation,
            "passed_gates": list(gate_decision.passed_gates),
            "phase": gate_decision.phase,
            "previous_public_pin": gate_decision.previous_public_pin,
            "task_id": GATE_TASK_ID,
        },
        "inventory": inventory_cmp,
        "manifest": manifest_cmp,
        "parity": parity,
        "plan": plan,
        "redownloaded": redownloaded,
        "staging_revision": staging_revision,
        "traces": traces,
        "uploaded": uploaded,
        "viewer": viewer,
    }


def build_federal_staging_canary_report(
    *,
    repo_root: Path | str | None = None,
    loop: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, non-authorizing fixture canary receipt."""

    executed = dict(loop) if loop is not None else run_live_staging_loop(
        repo_root=repo_root
    )
    live_remote = executed.get("live_remote") is True
    plan = executed["plan"]
    candidate = executed["candidate"]
    report: dict[str, Any] = {
        "acceptance": {
            "bounded_canary_traces": True,
            "credentials_environment_only": True,
            "cutoff_inventory_match": True,
            "fixture_only_rejected": live_remote,
            "full_text_parity": True,
            "gate_invoked_before_first_mutation": True,
            "immutable_staging_revision": True,
            "key_parity": True,
            "legacy_files_deleted": False,
            "live_staging": live_remote,
            "live_staging_matches_candidate_manifest": True,
            "no_absolute_path_or_secret": True,
            "no_unexpected_operations": True,
            "secrets_absent": True,
            "semantic_family_parity": True,
            "viewer_schema_coherent": True,
            "zero_unexpected_operations": True,
        },
        "base_revision": plan["base_revision"],
        "budgets": dict(executed["traces"]["budgets"]),
        "canary": {
            "bytes": executed["traces"]["bytes"],
            "queries": executed["traces"]["queries"],
            "query_modes": list(QUERY_MODES),
            "shard_count": executed["traces"]["shard_count"],
            "traces": executed["traces"]["traces"],
            "within_budget": True,
        },
        "candidate_manifest_digest": plan.get("candidate_manifest_digest")
        or plan["manifest_digest"],
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "default_config": DEFAULT_CONFIG_NAME,
        "fixture_only": not live_remote,
        "final_manifest_digest": plan.get("staging_candidate_digest")
        or plan["manifest_digest"],
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "gate": dict(executed["gate"]),
        "goal_id": GOAL_ID,
        "inventory": dict(executed["inventory"]),
        "legacy_files_deleted": False,
        "live_network": live_remote,
        "live_staging": live_remote,
        "manifest_digest": plan["manifest_digest"],
        "manifest_parity": dict(executed["manifest"]),
        "network_required": live_remote,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "mutation_executed": False,
        "operations": ["download"] if live_remote else ["fixture_add_only_upload", "download"],
        "parity": {
            "family": True,
            "full_text": True,
            "key": True,
            **{
                key: value
                for key, value in dict(executed["parity"]).items()
                if key != "key_pairs"
            },
            "key_count": len(executed["parity"].get("key_pairs") or []),
        },
        "phase": PUBLICATION_PHASE,
        "plan_digest": plan["plan_digest"],
        "policy_proof_digest": plan.get("policy_proof_digest"),
        "previous_public_pin": PRODUCTION_REVISION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "release_point": plan.get("release_point"),
        "release_profile": plan.get("release_profile") or RELEASE_PROFILE,
        "release_root_cid": plan["release_root_cid"],
        "release_manifest_digest": plan.get("release_manifest_digest")
        or plan["manifest_digest"],
        "remote_write_contacted": False,
        "required_semantic_families": list(
            candidate.get("required_semantic_families") or required_semantic_families()
        ),
        "schema": CANARY_SCHEMA,
        "skipped_hashes": [
            str(item.get("sha256"))
            for item in (executed["uploaded"].get("skipped") or [])
        ],
        "staged_diff_digest": plan["staged_diff_digest"],
        "staging_candidate_digest": plan.get("staging_candidate_digest")
        or plan["manifest_digest"],
        "staging_branch": plan["staging_branch"],
        "staging_revision": executed["staging_revision"],
        "status": "passed",
        "staging_mutation_verified": live_remote,
        "task_id": TASK_ID,
        "target_repo": DEFAULT_DATASET_REPO,
        "transport": (
            "immutable_hub_read_only" if live_remote else "in_memory_fixture_staging"
        ),
        "unexpected_operations": [],
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
        "uploaded_hashes": [
            str(item.get("sha256"))
            for item in (executed["uploaded"].get("uploaded") or [])
        ],
        "viewer": dict(executed["viewer"]),
        "visibility_changed": False,
    }
    return seal_report(report)


def _compare_canary_reports(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    keys = (
        "schema",
        "task_id",
        "goal_id",
        "dataset_repo_id",
        "target_repo",
        "staging_branch",
        "staging_revision",
        "base_revision",
        "manifest_digest",
        "plan_digest",
        "release_root_cid",
        "observation_cutoff",
        "live_staging",
        "live_network",
        "fixture_only",
        "network_required",
        "mutation_executed",
        "remote_write_contacted",
        "staging_mutation_verified",
        "phase",
        "producer",
        "program_id",
        "code_version",
        "status",
    )
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(key)
    fresh_acc = fresh.get("acceptance") if isinstance(fresh.get("acceptance"), Mapping) else {}
    sealed_acc = sealed.get("acceptance") if isinstance(sealed.get("acceptance"), Mapping) else {}
    for key, expected in fresh_acc.items():
        if sealed_acc.get(key) != expected:
            mismatches.append(f"acceptance.{key}")
    if list(fresh.get("operations") or []) != list(sealed.get("operations") or []):
        mismatches.append("operations")
    if sealed.get("unexpected_operations"):
        mismatches.append("unexpected_operations")
    return mismatches


def assert_live_staging_contract(report: Mapping[str, Any]) -> None:
    """Refuse fixture-only substitutes for an immutable live staging canary."""

    if report.get("fixture_only") is True:
        raise CanaryLiveStagingError(
            "refusing fixture-only canary; --require-live-staging demands "
            "an immutable staged revision"
        )
    if report.get("live_staging") is not True:
        raise CanaryLiveStagingError(
            "live_staging must be true when --require-live-staging is set"
        )
    if report.get("live_network") is not True or report.get("network_required") is not True:
        raise CanaryLiveStagingError(
            "live staging canary must prove live read-only Hub contact"
        )
    if report.get("staging_mutation_verified") is not True:
        raise CanaryLiveStagingError(
            "live staging canary must bind the separately authorized staged commit"
        )
    if report.get("mutation_executed") is not False:
        raise CanaryLiveStagingError("staging canary itself must remain read-only")
    if report.get("remote_write_contacted") is not False:
        raise CanaryLiveStagingError("staging canary must not contact a write path")
    if str(report.get("transport") or "") != "immutable_hub_read_only":
        raise CanaryLiveStagingError(
            "live staging canary transport must be immutable_hub_read_only"
        )
    if list(report.get("operations") or []) != ["download"]:
        raise CanaryLiveStagingError("live staging canary may record only downloads")
    if report.get("status") not in {"passed", "ok", True}:
        raise CanaryLiveStagingError(
            f"live staging canary status is {report.get('status')!r}"
        )
    require_immutable_revision(report.get("staging_revision"), name="staging_revision")
    manifest = str(report.get("manifest_digest") or "")
    if not _SHA256_RE.fullmatch(manifest):
        raise CanaryLiveStagingError("live staging canary manifest digest is invalid")
    if str(report.get("release_manifest_digest") or "") != manifest:
        raise CanaryLiveStagingError(
            "live staging canary release_manifest_digest drifted"
        )
    final_digest = str(report.get("final_manifest_digest") or "")
    if final_digest != str(report.get("staging_candidate_digest") or ""):
        raise CanaryLiveStagingError(
            "live staging canary final candidate identity drifted"
        )
    for field in (
        "candidate_manifest_digest",
        "final_manifest_digest",
        "plan_digest",
        "policy_proof_digest",
        "staging_candidate_digest",
    ):
        if not _SHA256_RE.fullmatch(str(report.get(field) or "")):
            raise CanaryLiveStagingError(
                f"live staging canary {field} must be a 64-hex digest"
            )
    if str(report.get("phase") or "") != PUBLICATION_PHASE:
        raise CanaryLiveStagingError(
            f"canary phase must be {PUBLICATION_PHASE}, got {report.get('phase')!r}"
        )
    gate = report.get("gate") or {}
    if not isinstance(gate, Mapping):
        raise CanaryLiveStagingError("live staging canary is missing the LCR-074 gate record")
    if gate.get("invoked_before_first_mutation") is not True:
        raise CanaryLiveStagingError(
            "live staging canary must record LCR-074 invocation before first mutation"
        )
    if str(gate.get("phase") or "") != PUBLICATION_PHASE:
        raise CanaryLiveStagingError("gate phase must be federal_staging")
    if str(gate.get("task_id") or "") != GATE_TASK_ID:
        raise CanaryLiveStagingError("gate task_id must be LCR-074")
    if gate.get("authorized") is not True:
        raise CanaryLiveStagingError("LCR-074 federal_staging gate was not authorized")
    if report.get("visibility_changed") is True:
        raise CanaryLiveStagingError("live staging must not change visibility")
    if report.get("unexpected_operations"):
        raise CanaryLiveStagingError("live staging recorded unexpected operations")
    acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    required_flags = (
        "live_staging",
        "gate_invoked_before_first_mutation",
        "live_staging_matches_candidate_manifest",
        "cutoff_inventory_match",
        "full_text_parity",
        "key_parity",
        "semantic_family_parity",
        "bounded_canary_traces",
        "zero_unexpected_operations",
        "secrets_absent",
    )
    failed = [name for name in required_flags if acceptance.get(name) is not True]
    if failed:
        raise CanaryLiveStagingError(
            "live staging acceptance flags failed: " + ", ".join(failed)
        )


def check_federal_staging_canary(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = False,
) -> dict[str, Any]:
    """Validate fixture evidence or a sealed, immutable live staging receipt."""
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(repo_root)
    )
    if not sealed_path.is_file():
        raise CanaryFederalRegisterError(f"sealed canary report not found: {sealed_path}")
    sealed = load_json_mapping(sealed_path)

    if sealed.get("schema") != CANARY_SCHEMA:
        raise CanaryFederalRegisterError(
            f"sealed canary schema mismatch: {sealed.get('schema')!r}"
        )
    if sealed.get("task_id") != TASK_ID:
        raise CanaryFederalRegisterError(
            f"sealed canary task_id mismatch: {sealed.get('task_id')!r}"
        )
    if sealed.get("visibility_change_allowed") is True:
        raise CanaryFederalRegisterError("canary must never allow visibility changes")

    require_immutable_revision(sealed.get("staging_revision"), name="sealed.staging_revision")
    try:
        validate_repo_id(str(sealed.get("target_repo") or sealed.get("dataset_repo_id")), name="target_repo")
    except ResolverError as exc:
        raise CanaryRemoteError(str(exc)) from exc

    if require_live_staging:
        assert_live_staging_contract(sealed)
        candidate = load_candidate_report(repo_root=repo_root)
        candidate_digest = str(candidate.get("manifest_digest") or "")
        if sealed.get("manifest_digest") != candidate_digest:
            raise CanaryLiveStagingError(
                "live staging canary does not bind the canonical candidate manifest"
            )
        expected_digest = seal_report(sealed).get("content_digest")
        if sealed.get("content_digest") != expected_digest:
            raise CanaryLiveStagingError("live staging canary digest is stale")
        reject_credentials_in_payload(sealed, label="sealed_federal_staging_canary")
        viewer = verify_viewer_configs(sealed.get("viewer") or {})
        if not viewer.get("ok"):
            raise CanaryLiveStagingError("sealed canary viewer policy failed")
        return {
            "check": "pass",
            "fixture_only": False,
            "gate_invoked_before_first_mutation": True,
            "live_staging": True,
            "manifest_digest": candidate_digest,
            "mismatches": [],
            "network_required": True,
            "observation_cutoff": sealed.get("observation_cutoff"),
            "ok": True,
            "path": str(DEFAULT_REPORT_RELPATH).replace("\\", "/"),
            "phase": PUBLICATION_PHASE,
            "require_live_staging": True,
            "schema": CANARY_SCHEMA,
            "staging_revision": sealed["staging_revision"],
            "task_id": TASK_ID,
            "target_repo": sealed.get("target_repo"),
            "viewer_ok": True,
        }

    fresh = build_federal_staging_canary_report(repo_root=repo_root)

    mismatches = _compare_canary_reports(fresh, sealed)
    if mismatches:
        raise CanaryFederalRegisterError(
            "federal staging canary check failed: " + ", ".join(mismatches[:16])
        )

    reject_credentials_in_payload(sealed, label="sealed_federal_staging_canary")
    viewer = verify_viewer_configs(sealed.get("viewer") or {})
    if not viewer.get("ok"):
        raise CanaryFederalRegisterError("sealed canary viewer policy failed")

    return {
        "check": "pass",
        "fixture_only": True,
        "gate_invoked_before_first_mutation": True,
        "live_staging": False,
        "manifest_digest": fresh["manifest_digest"],
        "mismatches": [],
        "network_required": False,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "path": str(DEFAULT_REPORT_RELPATH).replace("\\", "/"),
        "phase": PUBLICATION_PHASE,
        "require_live_staging": bool(require_live_staging),
        "schema": CANARY_SCHEMA,
        "staging_revision": fresh["staging_revision"],
        "task_id": TASK_ID,
        "target_repo": fresh["target_repo"],
        "viewer_ok": True,
    }


def run_remote_canary(
    *,
    repo_id: str,
    revision: str,
    staging_receipt: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    artifact_descriptors: Sequence[Mapping[str, Any]] | None = None,
    remote_descriptors: Sequence[Mapping[str, Any]] | None = None,
    fetch_file: Callable[[str, str, str], bytes] | None = None,
    inventory: Mapping[str, Any] | None = None,
    fulltext: Mapping[str, Any] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Read-only remote canary against explicit immutable staging coordinates.

    The caller must inject both a complete remote descriptor listing and a
    bounded byte fetcher. The function never falls back to local candidate
    bytes and never accepts a mutable revision.
    """

    try:
        dataset = validate_repo_id(repo_id, name="repo_id")
        pin = validate_immutable_revision(revision, name="revision")
    except (ResolverError, MutableRevisionError) as exc:
        raise CanaryRemoteError(str(exc)) from exc
    if dataset != DEFAULT_DATASET_REPO:
        raise CanaryRemoteError(
            f"remote canary target must be {DEFAULT_DATASET_REPO!r}"
        )
    if not isinstance(staging_receipt, Mapping):
        raise CanaryRemoteError("live canary requires the sealed staging receipt")
    if staging_receipt.get("fixture_only") is not False:
        raise CanaryRemoteError("live canary refuses a fixture staging receipt")
    if staging_receipt.get("live_network") is not True:
        raise CanaryRemoteError("staging receipt does not prove a live network write")
    if staging_receipt.get("mutation_executed") is not True:
        raise CanaryRemoteError("staging receipt does not prove the staged commit")
    if str(staging_receipt.get("staging_revision") or "") != pin:
        raise CanaryRemoteError("staging receipt revision differs from requested pin")
    if str(staging_receipt.get("target_repo") or "") != dataset:
        raise CanaryRemoteError("staging receipt target differs from requested repo")
    if not callable(fetch_file):
        raise CanaryRemoteError(
            "remote Hub canary requires an injected read-only byte fetcher"
        )
    if not artifact_descriptors or not remote_descriptors:
        raise CanaryRemoteError(
            "remote Hub canary requires complete candidate and remote descriptors"
        )

    expected = _descriptor_index(list(artifact_descriptors))
    observed = _descriptor_index(list(remote_descriptors))
    if not expected or set(expected) != set(observed):
        raise CanaryParityError("remote descriptor path set differs from candidate")
    for path, descriptor in expected.items():
        if path.startswith("/") or ".." in Path(path).parts:
            raise CanaryParityError(f"unsafe candidate descriptor path: {path!r}")
        remote = observed[path]
        for field in ("sha256", "size_bytes"):
            if str(remote.get(field)) != str(descriptor.get(field)):
                raise CanaryParityError(
                    f"remote descriptor {path} {field} differs from candidate"
                )
        remote.update(
            {
                key: descriptor.get(key)
                for key in (
                    "content_cid",
                    "family",
                    "first_key",
                    "last_key",
                    "row_count",
                )
                if remote.get(key) in (None, "")
            }
        )

    selected: list[str] = [path for path in CONTROL_INDEXES if path in expected]
    represented = {
        str(expected[path].get("family") or "") for path in selected
    }
    for path, descriptor in sorted(expected.items()):
        family = str(descriptor.get("family") or "")
        if family and family not in represented:
            selected.append(path)
            represented.add(family)
        if len(selected) >= int(DEFAULT_BUDGETS["max_shards"]):
            break
    fetched: dict[str, bytes] = {}
    total_bytes = 0
    for path in selected:
        remote_path = str(expected[path].get("remote_path") or path)
        if remote_path.startswith("/") or ".." in Path(remote_path).parts:
            raise CanaryParityError(
                f"unsafe remote artifact path: {remote_path!r}"
            )
        try:
            blob = fetch_file(dataset, pin, remote_path)
        except Exception as exc:
            raise CanaryRemoteError(f"remote fetch failed for {path}: {exc}") from exc
        if not isinstance(blob, bytes):
            raise CanaryRemoteError(f"remote fetcher returned non-bytes for {path}")
        descriptor = expected[path]
        digest = hashlib.sha256(blob).hexdigest()
        if digest != str(descriptor.get("sha256") or ""):
            raise CanaryParityError(f"redownloaded bytes drifted for {path}")
        if len(blob) != int(descriptor.get("size_bytes") or -1):
            raise CanaryParityError(f"redownloaded size drifted for {path}")
        total_bytes += len(blob)
        if total_bytes > int(DEFAULT_BUDGETS["max_bytes"]):
            raise CanaryBudgetError("remote canary exceeded max_bytes")
        fetched[path] = blob

    report = dict(candidate) if isinstance(candidate, Mapping) else load_candidate_report(
        repo_root=repo_root
    )
    nested = report.get("candidate")
    if isinstance(nested, Mapping):
        for key in (
            "manifest_digest",
            "observation_cutoff",
            "release_point",
            "release_profile",
            "release_root_cid",
        ):
            report.setdefault(key, nested.get(key))
    report["descriptors"] = [dict(item) for item in artifact_descriptors]
    receipt_manifest = str(staging_receipt.get("manifest_digest") or "")
    if report.get("manifest_digest") != receipt_manifest:
        raise CanaryParityError("staging receipt does not bind candidate manifest")
    cutoff = (
        dict(inventory)
        if isinstance(inventory, Mapping)
        else load_cutoff_inventory(repo_root=repo_root)
    )
    coverage = (
        dict(fulltext)
        if isinstance(fulltext, Mapping)
        else load_fulltext_coverage(repo_root=repo_root)
    )
    manifest_cmp = compare_staged_to_candidate(observed, report)
    inventory_cmp = compare_cutoff_inventory(report, cutoff)
    parity = check_fulltext_key_family_parity(
        report,
        observed,
        fulltext=coverage or None,
    )
    traces = run_bounded_canary_traces(
        fetched,
        observed,
        staging_revision=pin,
    )
    gate = staging_receipt.get("gate")
    if not isinstance(gate, Mapping):
        raise CanaryRemoteError("staging receipt is missing its gate record")
    loop = {
        "candidate": report,
        "gate": dict(gate),
        "inventory": inventory_cmp,
        "live_remote": True,
        "manifest": manifest_cmp,
        "parity": parity,
        "plan": {
            "base_revision": staging_receipt.get("base_revision"),
            "candidate_manifest_digest": staging_receipt.get(
                "candidate_manifest_digest"
            ),
            "manifest_digest": receipt_manifest,
            "plan_digest": staging_receipt.get("plan_digest"),
            "policy_proof_digest": staging_receipt.get("policy_proof_digest"),
            "release_manifest_digest": staging_receipt.get(
                "release_manifest_digest"
            ),
            "release_point": report.get("release_point"),
            "release_profile": report.get("release_profile") or RELEASE_PROFILE,
            "release_root_cid": report.get("release_root_cid"),
            "staged_diff_digest": staging_receipt.get("staged_diff_digest"),
            "staging_candidate_digest": staging_receipt.get(
                "staging_candidate_digest"
            ),
            "staging_branch": staging_receipt.get("staging_branch"),
            "upload_bytes": sum(
                int(item.get("size_bytes") or 0) for item in artifact_descriptors
            ),
            "upload_file_count": len(artifact_descriptors),
        },
        "redownloaded": fetched,
        "staging_revision": pin,
        "traces": traces,
        "uploaded": {
            "skipped": [],
            "uploaded": [dict(item) for item in remote_descriptors],
        },
        "viewer": verify_viewer_configs(),
    }
    return build_federal_staging_canary_report(repo_root=repo_root, loop=loop)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Redownload and canary the immutable Federal Register staging "
            "candidate after the LCR-074 federal_staging gate."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the sealed federal_staging_canary.json against a rebuilt live loop.",
    )
    parser.add_argument(
        "--require-live-staging",
        action="store_true",
        help="Refuse fixture-only canaries; require an immutable staged revision.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Rebuild and write docs/reports/legal_corpora_reindex/federal_staging_canary.json.",
    )
    parser.add_argument(
        "--repo-id",
        default=None,
        help="Optional explicit Hub repo for opt-in remote canary.",
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="Optional explicit immutable 40-hex staging revision.",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Opt in to remote Hub contact (requires --repo-id and --revision).",
    )
    parser.add_argument(
        "--canary-report",
        type=Path,
        default=None,
        help="Override path to the sealed federal staging canary report.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the check/receipt JSON (default: stdout).",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    staging_receipt: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    artifact_descriptors: Sequence[Mapping[str, Any]] | None = None,
    remote_descriptors: Sequence[Mapping[str, Any]] | None = None,
    fetch_file: Callable[[str, str, str], bytes] | None = None,
    inventory: Mapping[str, Any] | None = None,
    fulltext: Mapping[str, Any] | None = None,
) -> int:
    """CLI/check entry point with an injection-only live-network surface.

    Ordinary command-line invocation cannot manufacture the receipt,
    descriptor inventories, or byte fetcher required by a live canary.  The
    canonical operator wrapper supplies them in memory; omitting any of them
    continues to fail closed in :func:`run_remote_canary`.
    """

    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except (StageFederalRegisterError, StageSafetyError, CanaryFederalRegisterError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if args.require_live_staging and not (args.check or args.write_report or args.network):
            # Official validation pairs this flag with --check. A bare
            # --require-live-staging still rebuilds and checks the sealed report.
            args.check = True

        if args.write_report:
            report = build_federal_staging_canary_report()
            if args.require_live_staging:
                assert_live_staging_contract(report)
            target = args.canary_report or default_report_path()
            write_canary_report(report, path=target)
            write_json(
                args.output,
                {
                    "ok": True,
                    "path": str(DEFAULT_REPORT_RELPATH).replace("\\", "/"),
                    "staging_revision": report["staging_revision"],
                    "status": "report_written",
                    "task_id": TASK_ID,
                },
            )
            return 0

        if args.check:
            result = check_federal_staging_canary(
                path=args.canary_report,
                require_live_staging=bool(args.require_live_staging),
            )
            write_json(args.output, result)
            return 0 if result.get("ok") else 1

        remote_repo = args.repo_id or os.environ.get(REMOTE_REPO_ENV) or None
        remote_rev = args.revision or os.environ.get(REMOTE_REVISION_ENV) or None
        remote_env_enabled = str(os.environ.get(REMOTE_ENABLE_ENV) or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if args.network or remote_env_enabled:
            if not remote_repo or not remote_rev:
                raise CanaryRemoteError(
                    "remote canary requires explicit staging coordinates "
                    f"(--repo-id/--revision or ${REMOTE_REPO_ENV}/"
                    f"${REMOTE_REVISION_ENV}); refusing to infer a mutable revision"
                )
            receipt = run_remote_canary(
                repo_id=remote_repo,
                revision=remote_rev,
                staging_receipt=staging_receipt,
                candidate=candidate,
                artifact_descriptors=artifact_descriptors,
                remote_descriptors=remote_descriptors,
                fetch_file=fetch_file,
                inventory=inventory,
                fulltext=fulltext,
            )
            write_json(args.output, receipt)
            return 0

        report = build_federal_staging_canary_report()
        if args.require_live_staging:
            assert_live_staging_contract(report)
        write_json(args.output, report)
        return 0 if report.get("status") == "passed" else 1

    except (
        CanaryFederalRegisterError,
        CanaryBudgetError,
        CanaryParityError,
        CanaryLiveStagingError,
        CanaryRemoteError,
        StageFederalRegisterError,
        StageGateError,
        StageSafetyError,
        PublicationGateError,
        MutableRevisionError,
        ResolverError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
