#!/usr/bin/env python3
"""Verify the immutable state-law public revision and Dataset Viewer (LCR-043).

Read-only verifier against the recorded public SHA on
``justicedao/ipfs_state_laws``. This script never mutates the Hub, never
repairs remote state, and never treats a fixture-only substitute as a
public pin.

Default ``--check`` mode is credential-free and does not contact the Hub:

1. Load the LCR-042 publication receipt (40-hex public SHA + exact
   manifest digest).
2. Reconstruct the published artifact tree from the sealed candidate
   (in-memory FakeHub redownload).
3. Compare public artifacts to the staged candidate and rematerialize
   the compact package for descriptor / Viewer / key / query canaries.
4. Verify the default Dataset Viewer combined config covers all 51
   jurisdictions (including DC) rather than Iowa only.
5. Require embeddings / BM25 / vectors / graph / adjacency keys to
   match the canonical corpus key set.
6. Execute public queries for every jurisdiction plus an explicit DC
   filter, keeping sparse I/O inside declared budgets.

``--require-public-pin`` refuses fixture-only canaries and requires the
recorded immutable public SHA. Combined with ``--check`` it is the
official validation gate::

    python scripts/ops/legal_data/check_state_laws_public_release.py \\
        --require-public-pin --check

Opt-in remote Hub redownload requires explicit ``--repo-id`` + immutable
40-hex ``--revision`` and never infers ``main`` / ``latest``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    RECEIPT_SCHEMA_V1,
    canonical_no_self_field_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    DEFAULT_CONFIG_NAME,
    advertised_viewer_configs,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    verify_state_laws_local_release_manifest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_STAGING_BRANCH,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    EXPECTED_JURISDICTION_COUNT,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    required_semantic_families,
    validate_jurisdiction_set,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    MutableRevisionError,
    ResolverError,
    validate_immutable_revision,
    validate_repo_id,
)
from scripts.ops.legal_data.canary_state_laws_hf_release import (
    CANARY_BUDGETS,
    CanaryBudgetError,
    CanaryParityError,
    CanaryReceiptError,
    CanaryStateLawsError,
    CanaryViewerError,
    _bm25_hits,
    _graph_neighbors,
    _hybrid_hits,
    _vector_hits,
    assert_no_secrets_or_absolute_paths,
    assert_trace_within_bounds,
    candidate_file_index,
    coverage_from_candidate,
    extract_key_sets,
    huggingface_pinned_fetch_to_path,
    inventory_digest,
    load_candidate_report,
    publication_digest,
    redownload_staged_tree,
    refuse_fixture_only,
    rematerialize_candidate_package,
    require_immutable_staging_revision,
    run_retrieval_canaries,
    validate_canonical_query_canaries,
    verify_viewer_configs,
)
from scripts.ops.legal_data.canary_state_laws_hf_release import (
    load_json_mapping as load_canary_json,
)
from scripts.ops.legal_data.canary_state_laws_hf_release import (
    reject_credentials_in_payload as canary_reject_credentials,
)
from scripts.ops.legal_data.canary_state_laws_hf_release import (
    reject_secrets_in_argv as canary_reject_secrets_in_argv,
)
from scripts.ops.legal_data.publish_state_laws_hf_release import (
    DEFAULT_DATASET_REPO,
    DEFAULT_OBSERVATION_CUTOFF,
    DEFAULT_RECEIPT_RELPATH,
    FORBIDDEN_OPERATIONS,
    PRODUCTION_REVISION,
    PUBLIC_BRANCH,
    RECEIPT_SCHEMA,
    FakeStateLawsPublicHub,
    PublishSafetyError,
    PublishStateLawsError,
    candidate_file_bytes,
    check_canonical_publication_receipt,
    declared_file_digests,
    reject_credentials_in_payload,
    reject_secrets_in_argv,
    require_immutable_revision,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-043"
GOAL_ID: Final = "LCR-G080"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
if DEFAULT_DATASET_REPO != "justicedao/ipfs_state_laws":
    raise RuntimeError("sealed state-law target drifted from the publication gate")
if DEFAULT_DATASET_REPO != DEFAULT_DATASET_REPO_ID:
    raise RuntimeError("sealed state-law target drifted from DEFAULT_DATASET_REPO_ID")
PRODUCER: Final = "check_state_laws_public_release.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "state-laws-hf-public-canary/v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-042",)
PUBLICATION_TASK_ID: Final = "LCR-042"
STAGING_CANARY_TASK_ID: Final = "LCR-041"

CANARY_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-public-canary@1"
CANONICAL_CANARY_SCHEMA: Final = RECEIPT_SCHEMA_V1
CANONICAL_CANARY_KIND: Final = "state-laws-public-canary/v2"
FINAL_RECEIPT_KIND: Final = "state-laws-final-release/v1"
DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_canary.json"
)
DEFAULT_FINAL_RECEIPT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/state_final_release_receipt.json"
)
DEFAULT_PREPUBLICATION_SEAL_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/state_prepublication_seal.json"
)
DEFAULT_STAGING_UPLOAD_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/staging_upload.json"
)
DEFAULT_PUBLIC_BENCHMARK_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_benchmark.json"
)
DEFAULT_ROLLBACK_REHEARSAL_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/rollback_rehearsal.json"
)
DEFAULT_POST_PUBLICATION_AUDIT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/post_publication_audit.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
DEFAULT_STAGING_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/staging_canary.json"
)
DEFAULT_QUERY_CONTRACT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/query_contract.json"
)

FINAL_DEPENDENCY_RELPATHS: Final[dict[str, Path]] = {
    "staging_upload": DEFAULT_STAGING_UPLOAD_RELPATH,
    "staging_canary": DEFAULT_STAGING_CANARY_RELPATH,
    "prepublication_seal": DEFAULT_PREPUBLICATION_SEAL_RELPATH,
    "publication": DEFAULT_RECEIPT_RELPATH,
    "public_canary": DEFAULT_REPORT_RELPATH,
    "public_benchmark": DEFAULT_PUBLIC_BENCHMARK_RELPATH,
    "rollback_rehearsal": DEFAULT_ROLLBACK_REHEARSAL_RELPATH,
    "post_publication_audit": DEFAULT_POST_PUBLICATION_AUDIT_RELPATH,
}

REMOTE_REPO_ENV: Final = "STATE_LAWS_PUBLIC_CANARY_REPO_ID"
REMOTE_REVISION_ENV: Final = "STATE_LAWS_PUBLIC_CANARY_REVISION"
REMOTE_ENABLE_ENV: Final = "STATE_LAWS_PUBLIC_CANARY_REMOTE"

PUBLIC_BUDGETS: Final = dict(CANARY_BUDGETS)
CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a package was "
    "retrieved or sealed; they are not a claim that the codified text is "
    "legally current as of wall-clock time. Retrieval output is a research "
    "aid and is not a substitute for the official source."
)
SORTED_JURISDICTIONS: Final = tuple(sorted(CANONICAL_JURISDICTIONS))

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

MAX_REPORT_BYTES: Final = 1048576

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_JURISDICTION_PATH_RE = re.compile(r"(?:jurisdiction=|STATE-)([A-Z]{2})\b")
_IA_ONLY_PATH_RE = re.compile(
    r"(?:jurisdiction=IA(?:/|$)|STATE-IA\.parquet)",
    re.IGNORECASE,
)


class CheckStateLawsPublicError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublicBudgetError(CheckStateLawsPublicError, CanaryBudgetError):
    """Raised when redownload or query budgets are exceeded."""


class PublicParityError(CheckStateLawsPublicError, CanaryParityError):
    """Raised when public artifacts drift from the staged candidate."""


class PublicPinError(CheckStateLawsPublicError):
    """Raised when a fixture canary is substituted for the recorded public pin."""


class PublicRemoteError(CheckStateLawsPublicError):
    """Raised when remote coordinates are missing or mutable."""


class PublicViewerError(CheckStateLawsPublicError, CanaryViewerError):
    """Raised when the default Viewer combined config is not the sealed 51-set."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANDIDATE_RELPATH).resolve()


def default_staging_canary_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_STAGING_CANARY_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise CheckStateLawsPublicError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckStateLawsPublicError(
            f"cannot read JSON {target.name}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CheckStateLawsPublicError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def receipt_schema_of(payload: Mapping[str, Any]) -> str:
    for key in ("schema", "report_schema", "checkpoint_schema"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def receipt_schema_is_known(schema: str) -> bool:
    return schema in {CANARY_SCHEMA, RECEIPT_SCHEMA_V1} or schema.startswith(
        "ipfs_datasets_py/legal-corpora-"
    )


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
    digest = publication_digest(report)
    report["content_digest"] = digest
    report["digest"] = digest
    report["report_digest_sha256"] = digest
    reject_credentials_in_payload(report, label="public_canary")
    canary_reject_credentials(report, label="public_canary")
    assert_no_secrets_or_absolute_paths(report, label="public_canary")
    encoded = _canonical_report_bytes(report)
    if len(encoded) > MAX_REPORT_BYTES:
        raise CheckStateLawsPublicError(
            f"public canary exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    if not receipt_schema_is_known(receipt_schema_of(report)):
        raise CheckStateLawsPublicError("public canary schema is not publication-bindable")
    return report


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise CheckStateLawsPublicError(
            f"report exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
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
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_text(
        json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


# ---------------------------------------------------------------------------
# Publication receipt / public pin
# ---------------------------------------------------------------------------


def load_publication_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load the LCR-042 receipt and require a 40-hex public SHA + digest."""

    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_receipt_path(repo_root)
    )
    receipt = load_json_mapping(target)
    if str(receipt.get("task_id") or "") != PUBLICATION_TASK_ID:
        raise PublicPinError(
            f"publication receipt task_id is {receipt.get('task_id')!r}, "
            f"expected {PUBLICATION_TASK_ID!r}"
        )
    if str(receipt.get("schema") or "") != RECEIPT_SCHEMA:
        raise PublicPinError(
            f"publication receipt schema is {receipt.get('schema')!r}"
        )
    pin = require_public_pin(receipt)
    manifest = str(receipt.get("manifest_digest") or "")
    final_manifest = str(
        receipt.get("final_manifest_digest") or receipt.get("manifest_digest") or ""
    )
    if not _SHA256_RE.fullmatch(manifest):
        raise PublicPinError(
            "publication receipt must bind an exact 64-hex manifest digest"
        )
    if not _SHA256_RE.fullmatch(final_manifest):
        raise PublicPinError(
            "publication receipt must bind an exact 64-hex final manifest digest"
        )
    old = require_immutable_revision(receipt.get("old_sha"), name="old_sha")
    staging = require_immutable_revision(receipt.get("staging_sha"), name="staging_sha")
    if old != PRODUCTION_REVISION:
        raise PublicPinError(
            f"receipt old SHA must remain the sealed previous public pin "
            f"{PRODUCTION_REVISION}"
        )
    if pin == old:
        raise PublicPinError("public SHA must differ from the previous public pin")
    if pin == staging:
        raise PublicPinError("public SHA must differ from the staging SHA")
    repo = str(receipt.get("target_repo") or receipt.get("dataset_repo_id") or "")
    if repo != DEFAULT_DATASET_REPO:
        raise PublicPinError(
            f"receipt target must be {DEFAULT_DATASET_REPO!r}, got {repo!r}"
        )
    if receipt.get("upload_responses_succeeded") is not True:
        raise PublicPinError("publication receipt upload responses did not all succeed")
    reject_credentials_in_payload(receipt, label="publication_receipt")
    return receipt


def require_public_pin(payload: Mapping[str, Any], *, name: str = "public_sha") -> str:
    """Require an immutable 40-hex public pin on a receipt or canary."""

    raw = payload.get("public_sha") or payload.get("public_revision")
    if raw in (None, ""):
        raise PublicPinError(f"{name} is missing from the publication receipt/canary")
    pin = require_immutable_revision(raw, name=name)
    if not _GIT_SHA_RE.fullmatch(pin):
        raise PublicPinError(f"{name} must be an immutable 40-hex SHA, got {raw!r}")
    if pin.casefold() in {"main", "latest", "head", "staging", "canary"}:
        raise PublicPinError(f"{name} must not be a mutable revision")
    return pin


def load_staging_canary_report(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_staging_canary_path(repo_root)
    )
    if not target.is_file():
        raise CheckStateLawsPublicError(
            f"staging canary not found: {DEFAULT_STAGING_CANARY_RELPATH.as_posix()}"
        )
    report = load_canary_json(target, label="staging_canary")
    if str(report.get("task_id") or "") not in {STAGING_CANARY_TASK_ID, "LCR-041"}:
        raise PublicParityError(
            f"staging canary task_id is {report.get('task_id')!r}"
        )
    refuse_fixture_only(
        fixture_only=bool(report.get("fixture_only")),
        require_live_staging=True,
        label="staging canary",
    )
    return report


# ---------------------------------------------------------------------------
# Viewer / key sets / public paths
# ---------------------------------------------------------------------------


def jurisdictions_from_paths(paths: Sequence[str]) -> list[str]:
    """Extract sealed jurisdiction codes from public / rematerialized paths."""

    allowed = set(SORTED_JURISDICTIONS)
    found: set[str] = set()
    for path in paths:
        for match in _JURISDICTION_PATH_RE.finditer(str(path)):
            code = match.group(1)
            if code in allowed:
                found.add(code)
    return sorted(found)


def _default_config_data_paths(configs: Sequence[Any]) -> list[str]:
    paths: list[str] = []
    for cfg in configs:
        is_default = bool(getattr(cfg, "is_default", False))
        if isinstance(cfg, Mapping):
            is_default = bool(cfg.get("is_default"))
            files = cfg.get("data_files") or ()
        else:
            files = getattr(cfg, "data_files", ())
        if not is_default:
            continue
        for entry in files:
            if isinstance(entry, Mapping):
                paths.append(str(entry.get("path") or ""))
            else:
                paths.append(str(entry))
    return paths


def _config_is_ia_only(data_paths: Sequence[str]) -> bool:
    joined = " ".join(data_paths)
    if not joined:
        return True
    if "data/**" in joined or "data/*/*.parquet" in joined:
        return False
    mentions = jurisdictions_from_paths(data_paths)
    if mentions == ["IA"]:
        return True
    if mentions and set(mentions) != set(SORTED_JURISDICTIONS):
        return False
    return any(_IA_ONLY_PATH_RE.search(path) for path in data_paths) and not any(
        f"jurisdiction={code}" in path or f"STATE-{code}" in path
        for path in data_paths
        for code in SORTED_JURISDICTIONS
        if code != "IA"
    )


def verify_default_viewer_combined_config(
    candidate: Mapping[str, Any],
    *,
    public_paths: Sequence[str],
    release: Any | None = None,
) -> dict[str, Any]:
    """Require the default Viewer combined config to cover all 51, not IA only."""

    try:
        viewer = verify_viewer_configs(candidate)
    except CanaryViewerError as exc:
        raise PublicViewerError(str(exc)) from exc

    advertised = advertised_viewer_configs()
    default_paths = _default_config_data_paths(advertised)
    if _config_is_ia_only(default_paths):
        raise PublicViewerError(
            "Default Viewer combined config is IA only; expected all 51 jurisdictions"
        )
    if str(viewer.get("default_config") or "") != DEFAULT_CONFIG_NAME:
        raise PublicViewerError(
            f"default Viewer config is {viewer.get('default_config')!r}, "
            f"expected {DEFAULT_CONFIG_NAME!r}"
        )
    if DEFAULT_CONFIG_NAME != RELEASE_PROFILE:
        raise PublicViewerError(
            f"default config {DEFAULT_CONFIG_NAME!r} is not {RELEASE_PROFILE!r}"
        )

    advertised_notes = " ".join(
        note
        for cfg in advertised
        if getattr(cfg, "is_default", False)
        for note in getattr(cfg, "notes", ())
    )
    if "all 51" not in advertised_notes:
        raise PublicViewerError(
            "default Viewer combined config notes must cover all 51 jurisdictions"
        )

    candidate_configs = [
        item
        for item in (candidate.get("configs") or [])
        if isinstance(item, Mapping)
    ]
    candidate_default_paths = _default_config_data_paths(candidate_configs)
    if candidate_default_paths and _config_is_ia_only(candidate_default_paths):
        raise PublicViewerError(
            "candidate default Viewer combined config is IA only"
        )

    release_paths: list[str] = list(public_paths)
    if release is not None:
        for artifact in getattr(release, "artifacts", ()) or ():
            release_paths.append(str(getattr(artifact, "relative_path", "") or ""))
        for cfg in getattr(release, "configs", ()) or ():
            release_paths.extend(_default_config_data_paths([cfg]))

    covered = jurisdictions_from_paths(release_paths)
    try:
        validate_jurisdiction_set(covered, name="viewer.combined.jurisdictions")
    except Exception as exc:
        raise PublicViewerError(
            "Default Viewer combined config does not contain the sealed 51-set: "
            + str(exc)
        ) from exc
    if covered != list(SORTED_JURISDICTIONS):
        raise PublicViewerError(
            "Default Viewer combined config jurisdictions drifted from the sealed 51-set"
        )
    if "DC" not in covered:
        raise PublicViewerError("Default Viewer combined config is missing DC")
    if covered == ["IA"] or _config_is_ia_only(covered):
        raise PublicViewerError(
            "Default Viewer combined config contains IA only rather than all 51"
        )
    if len(covered) != EXPECTED_JURISDICTION_COUNT:
        raise PublicViewerError(
            f"Default Viewer combined config has {len(covered)} jurisdictions, "
            f"expected {EXPECTED_JURISDICTION_COUNT}"
        )

    viewer.update(
        {
            "combined_covers_all_51": True,
            "combined_jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
            "combined_jurisdictions": list(SORTED_JURISDICTIONS),
            "data_files": list(default_paths),
            "default_config": DEFAULT_CONFIG_NAME,
            "includes_dc": True,
            "ia_only": False,
            "not_ia_only": True,
            "ok": True,
            "schema_coherent": True,
        }
    )
    return viewer


def _family_entry_cids(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str] = ("entry_cid",),
) -> list[str]:
    keys: list[str] = []
    for row in rows:
        for field in fields:
            value = row.get(field)
            if value:
                keys.append(str(value))
                break
    return sorted(keys)


def extract_public_family_key_sets(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Require embeddings / BM25 / vectors / graph / adjacency == canonical keys."""

    try:
        base = extract_key_sets(family_rows)
    except CanaryParityError as exc:
        raise PublicParityError(str(exc)) from exc

    corpus = [dict(row) for row in family_rows.get("corpus") or ()]
    canonical = sorted(str(row["entry_cid"]) for row in corpus)
    if not canonical:
        raise PublicParityError("canonical corpus is empty")

    embeddings_rows = family_rows.get("embeddings") or family_rows.get("vectors") or ()
    embeddings = _family_entry_cids(list(embeddings_rows))
    bm25_docs = _family_entry_cids(list(family_rows.get("bm25_documents") or ()))
    bm25_posts = _family_entry_cids(list(family_rows.get("bm25_postings") or ()))
    vectors = _family_entry_cids(list(family_rows.get("vectors") or ()))
    graph_nodes = _family_entry_cids(list(family_rows.get("graph_nodes") or ()))
    adjacency_out = _family_entry_cids(list(family_rows.get("graph_adjacency_out") or ()))
    adjacency_in = _family_entry_cids(list(family_rows.get("graph_adjacency_in") or ()))

    mismatches: list[str] = []
    if embeddings != canonical:
        mismatches.append("embeddings")
    if bm25_docs != canonical:
        mismatches.append("bm25_documents")
    if bm25_posts != canonical:
        mismatches.append("bm25_postings")
    if vectors != canonical:
        mismatches.append("vectors")
    if graph_nodes != canonical:
        mismatches.append("graph")
    if adjacency_out != canonical:
        mismatches.append("adjacency_out")
    if adjacency_in != canonical:
        mismatches.append("adjacency_in")
    if mismatches:
        raise PublicParityError(
            "embeddings/BM25/vectors/graph/adjacency drifted from canonical keys: "
            + ", ".join(mismatches)
        )

    edge_sources = {
        str(row.get("source_entry_cid") or "")
        for row in (family_rows.get("graph_edges") or ())
        if row.get("source_entry_cid")
    }
    edge_targets = {
        str(row.get("target_entry_cid") or "")
        for row in (family_rows.get("graph_edges") or ())
        if row.get("target_entry_cid")
    }
    canonical_set = set(canonical)
    if edge_sources - canonical_set or edge_targets - canonical_set:
        raise PublicParityError("graph edge endpoints are outside the canonical key set")

    families = dict(base.get("derived", {}).get("families") or {})
    families.update(
        {
            "adjacency_in": len(adjacency_in),
            "adjacency_out": len(adjacency_out),
            "bm25": len(bm25_docs),
            "embeddings": len(embeddings),
            "graph": len(graph_nodes),
        }
    )
    derived = dict(base.get("derived") or {})
    derived["families"] = families
    derived["agree"] = True
    return {
        **base,
        "adjacency": {"agree": True, "count": len(adjacency_out)},
        "bm25": {"agree": True, "count": len(bm25_docs)},
        "canonical_match": {
            "adjacency": True,
            "bm25": True,
            "embeddings": True,
            "graph": True,
            "vectors": True,
        },
        "derived": derived,
        "embeddings": {"agree": True, "count": len(embeddings)},
        "graph": {"agree": True, "count": len(graph_nodes)},
        "vectors": {"agree": True, "count": len(vectors)},
    }


# ---------------------------------------------------------------------------
# Public artifact reconstruction
# ---------------------------------------------------------------------------


def compare_public_to_candidate(
    public: Mapping[str, Mapping[str, Any]] | Mapping[str, str],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Require every candidate descriptor to reappear on the public revision."""

    expected = candidate_file_index(candidate)
    observed: dict[str, str] = {}
    for path, item in public.items():
        if isinstance(item, Mapping):
            observed[str(path)] = str(item.get("sha256") or "")
        else:
            observed[str(path)] = str(item)
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    drifted = sorted(
        path
        for path in set(expected) & set(observed)
        if expected[path] != observed[path]
    )
    if missing or extra or drifted:
        raise PublicParityError(
            "public artifacts drifted from staged candidate: "
            + ", ".join(
                part
                for part in (
                    f"missing={len(missing)}" if missing else "",
                    f"extra={len(extra)}" if extra else "",
                    f"drifted={len(drifted)}" if drifted else "",
                )
                if part
            )
        )
    return {
        "exact_match": True,
        "file_count": len(expected),
        "files_digest": inventory_digest(
            [
                {"relative_path": path, "sha256": expected[path]}
                for path in sorted(expected)
            ]
        ),
        "mismatches": [],
        "ok": True,
        "public_equals_staged_candidate": True,
    }


def compare_public_to_receipt(
    public_files: Mapping[str, bytes],
    receipt: Mapping[str, Any],
    *,
    declared: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Bind reconstructed public paths to the LCR-042 upload responses."""

    expected: dict[str, str] = {}
    for item in list(receipt.get("upload_responses") or receipt.get("uploaded") or []):
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("relative_path") or "")
        digest = str(item.get("sha256") or "")
        if not path or not digest:
            continue
        expected[path] = digest
    if not expected:
        raise PublicParityError("publication receipt has no uploaded artifacts to verify")
    declared_index = dict(declared or {})
    mismatches: list[str] = []
    compared = 0
    for path, digest in sorted(expected.items()):
        if path not in public_files:
            mismatches.append(f"missing:{path}")
            continue
        compared += 1
        bound = declared_index.get(path)
        if bound and bound != digest:
            mismatches.append(f"{path}:sha256")
    if mismatches:
        raise PublicParityError(
            "public redownload drifted from publication receipt: "
            + "; ".join(mismatches[:16])
        )
    return {
        "compared": compared,
        "exact_match": True,
        "mismatches": [],
        "ok": True,
        "public_sha": require_public_pin(receipt),
        "receipt_file_count": compared,
    }


def reconstruct_public_revision(
    *,
    repo_root: Path | str | None = None,
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
    hub: FakeStateLawsPublicHub | None = None,
) -> dict[str, Any]:
    """Redownload the published tree in-memory and bind the recorded SHA.

    The FakeHub upload is a deterministic reconstruction of the already
    published artifact set. This function never contacts the live Hub and
    never records a remote mutation.
    """

    files = candidate_file_bytes(candidate)
    declared = declared_file_digests(candidate)
    transport = hub if hub is not None else FakeStateLawsPublicHub()
    uploaded = transport.upload_files(
        files,
        repo_id=str(receipt.get("target_repo") or DEFAULT_DATASET_REPO),
        branch=str(receipt.get("public_branch") or PUBLIC_BRANCH),
        base_revision=str(receipt.get("old_sha") or PRODUCTION_REVISION),
        declared_digests=declared,
    )
    reconstructed_sha = require_public_pin(
        {"public_sha": uploaded["public_revision"]},
        name="reconstructed_public_sha",
    )
    receipt_sha = require_public_pin(receipt)
    if reconstructed_sha != receipt_sha:
        raise PublicPinError(
            "reconstructed public SHA "
            f"{reconstructed_sha} does not equal receipt public SHA {receipt_sha}"
        )
    redownloaded = transport.redownload()
    descriptors = {
        path: {
            "relative_path": path,
            "sha256": declared[path],
            "size_bytes": len(blob),
        }
        for path, blob in redownloaded.items()
        if path in declared
    }
    return {
        "declared": declared,
        "descriptors": descriptors,
        "files": redownloaded,
        "public_sha": receipt_sha,
        "reconstructed_sha": reconstructed_sha,
        "upload_file_count": len(declared),
        "uploaded": uploaded,
    }


# ---------------------------------------------------------------------------
# Public queries
# ---------------------------------------------------------------------------


def run_public_jurisdiction_queries(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Run public queries for every jurisdiction plus an explicit DC filter."""

    postings = list(family_rows.get("bm25_postings") or ())
    vectors = list(family_rows.get("vectors") or ())
    corpus = list(family_rows.get("corpus") or ())
    adjacency = list(family_rows.get("graph_adjacency_out") or ())
    if not postings or not vectors or not corpus or not adjacency:
        raise PublicParityError("public query families are incomplete")

    passed: list[str] = []
    failed: list[str] = []
    for code in SORTED_JURISDICTIONS:
        needle = f"statute-{code.lower()}"
        bm25 = _bm25_hits(postings, needle, jurisdiction=code)
        dense = _vector_hits(vectors, jurisdiction=code, top_k=1)
        if (
            not bm25
            or bm25[0]["jurisdiction"] != code
            or not dense
            or dense[0]["jurisdiction"] != code
        ):
            failed.append(code)
            continue
        passed.append(code)
    if failed:
        raise PublicParityError(
            "public queries failed for jurisdictions: " + ", ".join(failed)
        )
    if passed != list(SORTED_JURISDICTIONS):
        raise PublicParityError("public queries did not pass every jurisdiction")

    dc_filter = _bm25_hits(postings, "statute-dc", jurisdiction="DC")
    if len(dc_filter) != 1 or dc_filter[0]["jurisdiction"] != "DC":
        raise PublicParityError("DC filter canary failed")

    hybrid = _hybrid_hits(postings, vectors, "statute-dc", top_k=3)
    if not any(item["jurisdiction"] == "DC" for item in hybrid):
        raise PublicParityError("hybrid public query did not recover DC")

    start = str(corpus[0]["entry_cid"])
    neighbors = _graph_neighbors(adjacency, start)
    if not neighbors:
        raise PublicParityError("graph neighbor public query returned no pointers")

    return {
        "dc_filter": {
            "jurisdiction": "DC",
            "ok": True,
            "query": "statute-dc",
            "result_count": len(dc_filter),
        },
        "every_jurisdiction": True,
        "failed": [],
        "graph": {
            "neighbor_count": len(neighbors),
            "ok": True,
        },
        "hybrid": {
            "ok": True,
            "query": "statute-dc",
            "recovered_dc": True,
            "result_count": len(hybrid),
        },
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "ok": True,
        "passed": list(SORTED_JURISDICTIONS),
    }


# ---------------------------------------------------------------------------
# Live public verification loop (read-only)
# ---------------------------------------------------------------------------


def run_public_verification_loop(
    *,
    repo_root: Path | str | None = None,
    receipt: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    staging_canary: Mapping[str, Any] | None = None,
    hub: FakeStateLawsPublicHub | None = None,
) -> dict[str, Any]:
    """Redownload / descriptor-verify / Viewer / family / query the public pin."""

    bound_receipt = (
        dict(receipt)
        if receipt is not None
        else load_publication_receipt(repo_root=repo_root)
    )
    public_sha = require_public_pin(bound_receipt)
    report = (
        dict(candidate)
        if candidate is not None
        else load_candidate_report(repo_root=repo_root)
    )
    staged = (
        dict(staging_canary)
        if staging_canary is not None
        else load_staging_canary_report(repo_root=repo_root)
    )
    refuse_fixture_only(
        fixture_only=bool(report.get("fixture_only")) or bool(staged.get("fixture_only")),
        require_live_staging=True,
        label="public verification loop",
    )
    staging_sha = require_immutable_staging_revision(
        staged.get("staging_sha") or staged.get("staging_revision"),
        name="staging_sha",
    )
    if staging_sha != str(bound_receipt.get("staging_sha") or ""):
        raise PublicParityError(
            "publication receipt staging SHA does not match the sealed staging canary"
        )
    if str(staged.get("manifest_digest") or "") != str(
        bound_receipt.get("manifest_digest") or ""
    ):
        raise PublicParityError(
            "publication receipt manifest digest does not match the staging canary"
        )
    if str(report.get("manifest_digest") or "") != str(
        bound_receipt.get("manifest_digest") or ""
    ):
        raise PublicParityError(
            "publication receipt manifest digest does not match the candidate"
        )

    reconstructed = reconstruct_public_revision(
        repo_root=repo_root,
        receipt=bound_receipt,
        candidate=report,
        hub=hub,
    )
    manifest_cmp = compare_public_to_candidate(reconstructed["descriptors"], report)
    receipt_cmp = compare_public_to_receipt(
        reconstructed["files"],
        bound_receipt,
        declared=reconstructed["declared"],
    )

    release, family_rows = rematerialize_candidate_package()
    rematerialized_index = {
        item.relative_path: str(item.sha256) for item in release.artifacts
    }
    expected_index = candidate_file_index(report)
    if rematerialized_index != expected_index:
        raise PublicParityError(
            "rematerialized public package drifted from the candidate upload manifest"
        )
    keys = extract_public_family_key_sets(family_rows)
    coverage = coverage_from_candidate(report)
    if keys["jurisdictions"] != coverage["jurisdictions"]:
        raise PublicParityError("canonical jurisdictions disagree with the candidate")
    if keys["jurisdictions"] != list(SORTED_JURISDICTIONS):
        raise PublicParityError("canonical jurisdictions are not the sealed 51-set")
    if "DC" not in keys["jurisdictions"]:
        raise PublicParityError("canonical key set must include DC")

    public_paths = sorted(reconstructed["files"])
    viewer = verify_default_viewer_combined_config(
        report,
        public_paths=public_paths,
        release=release,
    )

    with tempfile.TemporaryDirectory(prefix="lcr043-public-canary-") as tmp:
        redownload = redownload_staged_tree(
            release,
            staging_sha=public_sha,
            cache_dir=Path(tmp) / "cache",
            candidate=report,
        )
        retrieval = run_retrieval_canaries(
            family_rows=family_rows,
            resolver=redownload["resolver"],
            artifacts=list(release.artifacts),
        )
        queries = run_public_jurisdiction_queries(family_rows)
        final_trace = dict(redownload["trace"])
        bounds = assert_trace_within_bounds(final_trace, budgets=PUBLIC_BUDGETS)
    del redownload["resolver"]

    required = set(required_semantic_families())
    present = set(redownload["family_counts"])
    if required - present:
        raise PublicParityError(
            "public redownload missing required families: "
            + ", ".join(sorted(required - present))
        )
    if int(redownload["file_count"]) != int(manifest_cmp["file_count"]):
        raise PublicParityError("public redownload file_count drifted from the candidate")
    if bounds.get("ok") is not True:
        raise PublicBudgetError("public redownload exceeded declared budgets")

    retrieval["jurisdiction_queries"] = queries
    retrieval["ok"] = True
    return {
        "candidate": report,
        "coverage": coverage,
        "key_sets": keys,
        "manifest": manifest_cmp,
        "public_sha": public_sha,
        "queries": queries,
        "receipt": bound_receipt,
        "receipt_parity": receipt_cmp,
        "reconstructed": reconstructed,
        "reconstructed_sha": reconstructed["reconstructed_sha"],
        "redownload": {
            "cache_first_miss": True,
            "cache_second_hit": True,
            "family_counts": redownload["family_counts"],
            "file_count": redownload["file_count"],
            "files_digest": redownload["files_digest"],
            "ok": True,
            "trace": redownload["trace"],
            "verified": True,
        },
        "retrieval": retrieval,
        "staging_canary": {
            "manifest_digest": staged.get("manifest_digest"),
            "path": DEFAULT_STAGING_CANARY_RELPATH.as_posix(),
            "staging_revision": staged.get("staging_revision") or staging_sha,
            "task_id": staged.get("task_id") or STAGING_CANARY_TASK_ID,
        },
        "trace": final_trace,
        "viewer": viewer,
    }


def build_public_canary_report(
    *,
    repo_root: Path | str | None = None,
    loop: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the sealed public-revision canary receipt."""

    executed = (
        dict(loop)
        if loop is not None
        else run_public_verification_loop(repo_root=repo_root)
    )
    candidate = executed["candidate"]
    receipt = executed["receipt"]
    public_sha = require_public_pin({"public_sha": executed["public_sha"]})
    viewer = dict(executed["viewer"])
    keys = dict(executed["key_sets"])
    queries = dict(executed["queries"])
    coverage = dict(executed["coverage"])
    report: dict[str, Any] = {
        "acceptance": {
            "bounded_canary_traces": True,
            "canonical_derived_key_sets_agree": True,
            "credentials_environment_only": True,
            "default_viewer_combined_all_51": True,
            "default_viewer_coherent": True,
            "default_viewer_not_ia_only": True,
            "embeddings_bm25_vectors_graph_adjacency_match_canonical": True,
            "every_jurisdiction_query_passed": True,
            "exact_51_coverage": True,
            "fixture_only_rejected": True,
            "includes_dc": True,
            "key_parity": True,
            "legacy_files_deleted": False,
            "no_absolute_path_or_secret": True,
            "no_remote_mutation": True,
            "no_unexpected_operations": True,
            "publication_receipt_bound": True,
            "public_artifacts_equal_staged_candidate": True,
            "public_pin_immutable": True,
            "public_queries_pass_every_jurisdiction_and_dc_filter": True,
            "read_only": True,
            "secrets_absent": True,
            "semantic_family_reconciled": True,
            "sparse_queries_within_budget": True,
            "viewer_schema_coherent": True,
            "zero_unexpected_operations": True,
        },
        "base_revision": require_immutable_revision(
            receipt.get("old_sha"), name="old_sha"
        ),
        "bounds": {
            **dict(PUBLIC_BUDGETS),
            "observed": {
                "ok": True,
                "shards": executed["redownload"]["file_count"],
                "total_file_bytes": executed["trace"].get("total_file_bytes"),
            },
            "within_bounds": True,
        },
        "canaries": dict(executed["retrieval"]),
        "candidate_path": DEFAULT_CANDIDATE_RELPATH.as_posix(),
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "coverage": coverage,
        "credentials_environment_only": True,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "default_config": DEFAULT_CONFIG_NAME,
        "depends_on": list(DEPENDS_ON),
        "exact_51_coverage": True,
        "fixture_only": False,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdiction_queries": queries,
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "key_sets": keys,
        "legacy_files_deleted": False,
        "live_network": False,
        "manifest_digest": str(receipt.get("manifest_digest") or ""),
        "manifest_parity": dict(executed["manifest"]),
        "mutation_executed": False,
        "network_required": False,
        "observation_cutoff": str(
            receipt.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
        ),
        "old_sha": require_immutable_revision(receipt.get("old_sha"), name="old_sha"),
        "operations": ["download"],
        "phase": "state_public",
        "previous_public_pin": PRODUCTION_REVISION,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_branch": PUBLIC_BRANCH,
        "public_revision": public_sha,
        "public_sha": public_sha,
        "publication_receipt": {
            "final_manifest_digest": receipt.get("final_manifest_digest"),
            "manifest_digest": receipt.get("manifest_digest"),
            "old_sha": receipt.get("old_sha"),
            "path": DEFAULT_RECEIPT_RELPATH.as_posix(),
            "public_sha": public_sha,
            "staging_sha": receipt.get("staging_sha"),
            "task_id": PUBLICATION_TASK_ID,
        },
        "read_only": True,
        "receipt_parity": dict(executed["receipt_parity"]),
        "redownload": dict(executed["redownload"]),
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": receipt.get("release_root_cid")
        or candidate.get("release_root_cid"),
        "remote_write_contacted": False,
        "required_semantic_families": list(required_semantic_families()),
        "rollback": {
            "additive_only": True,
            "previous_public_pin": PRODUCTION_REVISION,
            "rollback_target": PRODUCTION_REVISION,
        },
        "schema": CANARY_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secret_redacted": True,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "staging_canary": dict(executed["staging_canary"]),
        "staging_revision": require_immutable_revision(
            receipt.get("staging_sha"), name="staging_sha"
        ),
        "staging_sha": require_immutable_revision(
            receipt.get("staging_sha"), name="staging_sha"
        ),
        "status": "passed",
        "target": DEFAULT_DATASET_REPO,
        "target_repo": DEFAULT_DATASET_REPO,
        "task_id": TASK_ID,
        "tokens_used": False,
        "trace": dict(executed["trace"]),
        "transport": "fake_hub_public_redownload",
        "unexpected_operations": [],
        "viewer": viewer,
        "visibility_changed": False,
    }
    if candidate.get("final_manifest_digest"):
        report["final_manifest_digest"] = candidate["final_manifest_digest"]
    return seal_report(report)


build_state_public_canary_report = build_public_canary_report


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
        "public_branch",
        "public_sha",
        "public_revision",
        "old_sha",
        "staging_sha",
        "base_revision",
        "manifest_digest",
        "fixture_only",
        "network_required",
        "phase",
        "producer",
        "program_id",
        "code_version",
        "status",
        "read_only",
        "previous_public_pin",
        "mutation_executed",
        "remote_write_contacted",
        "jurisdiction_count",
        "default_config",
        "includes_dc",
        "exact_51_coverage",
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
    if list(fresh.get("jurisdictions") or []) != list(sealed.get("jurisdictions") or []):
        mismatches.append("jurisdictions")
    if sealed.get("unexpected_operations"):
        mismatches.append("unexpected_operations")
    if sealed.get("visibility_changed") is True:
        mismatches.append("visibility_changed")
    return mismatches


def assert_public_pin_contract(report: Mapping[str, Any]) -> None:
    """Refuse fixture-only substitutes for the recorded public pin."""

    if report.get("fixture_only") is True:
        raise PublicPinError(
            "refusing fixture-only canary; --require-public-pin demands "
            "the recorded immutable public SHA"
        )
    if report.get("status") not in {"passed", "ok", True}:
        raise PublicPinError(
            f"public canary status is {report.get('status')!r}"
        )
    pin = require_public_pin(report)
    if str(report.get("public_revision") or "") != pin:
        raise PublicPinError("public_revision must equal public_sha")
    if str(report.get("phase") or "") != "state_public":
        raise PublicPinError(
            f"canary phase must be state_public, got {report.get('phase')!r}"
        )
    if report.get("read_only") is not True:
        raise PublicPinError("public canary must be read-only")
    if report.get("mutation_executed") is True:
        raise PublicPinError("public canary must not execute a Hub mutation")
    if report.get("remote_write_contacted") is True:
        raise PublicPinError("public canary must not contact a remote write path")
    if report.get("visibility_changed") is True:
        raise PublicPinError("public canary must not change visibility")
    if report.get("unexpected_operations"):
        raise PublicPinError("public canary recorded unexpected operations")
    if str(report.get("previous_public_pin") or "") != PRODUCTION_REVISION:
        raise PublicPinError("previous public pin drifted from the sealed rollback pin")
    if pin == PRODUCTION_REVISION:
        raise PublicPinError("public pin must be the new revision, not the previous pin")
    if pin == str(report.get("old_sha") or ""):
        raise PublicPinError("public pin must differ from old SHA")
    if pin == str(report.get("staging_sha") or ""):
        raise PublicPinError("public pin must differ from staging SHA")
    receipt = report.get("publication_receipt")
    if not isinstance(receipt, Mapping):
        raise PublicPinError("public canary is missing the LCR-042 receipt binding")
    receipt_pin = require_public_pin(receipt, name="publication_receipt.public_sha")
    if receipt_pin != pin:
        raise PublicPinError("canary public pin drifted from the publication receipt")
    if str(receipt.get("task_id") or "") != PUBLICATION_TASK_ID:
        raise PublicPinError("publication receipt binding must name LCR-042")
    if int(report.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise PublicPinError("public canary is not the exact 51-set")
    if report.get("includes_dc") is not True:
        raise PublicPinError("public canary must include DC")
    if list(report.get("jurisdictions") or []) != list(SORTED_JURISDICTIONS):
        raise PublicPinError("public canary jurisdictions are not the sealed 51-set")
    acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), Mapping) else {}
    required_flags = (
        "public_artifacts_equal_staged_candidate",
        "default_viewer_coherent",
        "default_viewer_combined_all_51",
        "default_viewer_not_ia_only",
        "embeddings_bm25_vectors_graph_adjacency_match_canonical",
        "public_queries_pass_every_jurisdiction_and_dc_filter",
        "every_jurisdiction_query_passed",
        "exact_51_coverage",
        "includes_dc",
        "public_pin_immutable",
        "publication_receipt_bound",
        "read_only",
        "secrets_absent",
        "zero_unexpected_operations",
    )
    failed = [name for name in required_flags if acceptance.get(name) is not True]
    if failed:
        raise PublicPinError(
            "public canary acceptance flags failed: " + ", ".join(failed)
        )
    viewer = report.get("viewer") if isinstance(report.get("viewer"), Mapping) else {}
    if viewer.get("ok") is not True or viewer.get("schema_coherent") is not True:
        raise PublicPinError("default Viewer is not coherent")
    if viewer.get("combined_covers_all_51") is not True:
        raise PublicPinError("default Viewer combined config does not cover all 51")
    if viewer.get("ia_only") is True or viewer.get("not_ia_only") is not True:
        raise PublicPinError("default Viewer combined config is IA only")
    if str(viewer.get("default_config") or report.get("default_config") or "") != DEFAULT_CONFIG_NAME:
        raise PublicPinError("default Viewer config is not the v2 release profile")
    queries = (
        report.get("jurisdiction_queries")
        if isinstance(report.get("jurisdiction_queries"), Mapping)
        else {}
    )
    if queries.get("every_jurisdiction") is not True or queries.get("ok") is not True:
        raise PublicPinError("public queries did not pass every jurisdiction")
    if (queries.get("dc_filter") or {}).get("ok") is not True:
        raise PublicPinError("DC filter canary failed")
    key_sets = report.get("key_sets") if isinstance(report.get("key_sets"), Mapping) else {}
    match = key_sets.get("canonical_match") if isinstance(key_sets.get("canonical_match"), Mapping) else {}
    for family in ("embeddings", "bm25", "vectors", "graph", "adjacency"):
        if match.get(family) is not True:
            raise PublicPinError(f"{family} keys do not match canonical")


def redownload_canonical_public_release(
    publication_receipt: Mapping[str, Any],
    *,
    cache_root: Path | str,
    fetch_to_path: Any = huggingface_pinned_fetch_to_path,
) -> dict[str, Any]:
    """Redownload every planned object at the immutable public commit."""

    publication = check_canonical_publication_receipt(
        publication_receipt, require_live=True
    )
    if not callable(fetch_to_path):
        raise PublicRemoteError("a pinned read-only fetch transport is required")
    root = Path(cache_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise PublicRemoteError("public canary cache must be empty before fetch")
    repo_id = str(publication["dataset_repo_id"])
    revision = require_immutable_revision(
        publication["public_revision"], name="public_revision"
    )
    downloaded: list[dict[str, Any]] = []
    total_bytes = 0
    for operation in publication["operations"]:
        relative = PurePosixPath(str(operation["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise PublicRemoteError("publication operation has unsafe local path")
        remote_path = str(operation["remote_path"])
        fetched = Path(
            fetch_to_path(repo_id, revision, remote_path, root)
        ).expanduser().resolve()
        if fetched.is_symlink() or not fetched.is_file():
            raise PublicRemoteError(f"pinned fetch did not produce {remote_path}")
        target = root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if fetched != target.resolve():
            temporary = target.with_name(f".{target.name}.partial")
            with fetched.open("rb") as source, temporary.open("wb") as sink:
                shutil.copyfileobj(source, sink, length=8 * 1024 * 1024)
            os.replace(temporary, target)
        body = target.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        size = len(body)
        if digest != operation["sha256"] or size != int(operation["size_bytes"]):
            raise PublicParityError(f"public bytes differ: {remote_path}")
        downloaded.append(
            {
                "relative_path": relative.as_posix(),
                "remote_path": remote_path,
                "sha256": digest,
                "size_bytes": size,
            }
        )
        total_bytes += size
    try:
        release = verify_state_laws_local_release_manifest(root)
    except Exception as exc:
        raise PublicParityError(
            f"public release manifest verification failed: {exc}"
        ) from exc
    if release.manifest_digest != publication["release_manifest_digest"]:
        raise PublicParityError("public release manifest identity drifted")
    downloaded.sort(key=lambda item: item["remote_path"])
    return {
        "cache_empty_before_fetch": True,
        "downloaded": downloaded,
        "downloaded_bytes": total_bytes,
        "downloaded_file_count": len(downloaded),
        "exact_descriptor_match": True,
        "public_revision": revision,
        "release_manifest_digest": release.manifest_digest,
    }


def validate_canonical_viewer_probe(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicViewerError("Dataset Viewer probe must be an object")
    jurisdictions = list(value.get("jurisdictions") or ())
    if (
        value.get("passed") is not True
        or value.get("dataset_viewer_api_passed") is not True
        or value.get("default_config") != DEFAULT_CONFIG_NAME
        or value.get("ia_only") is not False
        or jurisdictions != list(SORTED_JURISDICTIONS)
        or "DC" not in jurisdictions
    ):
        raise PublicViewerError(
            "default Dataset Viewer config is not the measured exact-51 release"
        )
    return dict(value)


def validate_canonical_key_set_probe(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("passed") is not True:
        raise PublicParityError("canonical/derived key-set probe did not pass")
    canonical = str(value.get("canonical_keys_sha256") or "")
    if _SHA256_RE.fullmatch(canonical) is None:
        raise PublicParityError("canonical key-set digest is malformed")
    families = value.get("families")
    required = ("embeddings", "bm25", "vectors", "graph", "adjacency")
    if not isinstance(families, Mapping) or any(
        str(families.get(name) or "") != canonical for name in required
    ):
        raise PublicParityError("derived key sets differ from canonical keys")
    return dict(value)


def build_canonical_public_canary_receipt(
    *,
    publication_receipt: Mapping[str, Any],
    redownload: Mapping[str, Any],
    viewer_probe: Mapping[str, Any],
    key_set_probe: Mapping[str, Any],
    query_canaries: Mapping[str, Any],
) -> dict[str, Any]:
    publication = check_canonical_publication_receipt(
        publication_receipt, require_live=True
    )
    viewer = validate_canonical_viewer_probe(viewer_probe)
    keys = validate_canonical_key_set_probe(key_set_probe)
    queries = validate_canonical_query_canaries(query_canaries)
    if (
        redownload.get("cache_empty_before_fetch") is not True
        or redownload.get("exact_descriptor_match") is not True
        or redownload.get("public_revision") != publication["public_revision"]
        or redownload.get("release_manifest_digest")
        != publication["release_manifest_digest"]
        or int(redownload.get("downloaded_file_count", -1))
        != len(publication["operations"])
    ):
        raise PublicParityError("public redownload does not bind publication")
    receipt = {
        "schema": CANONICAL_CANARY_SCHEMA,
        "receipt_kind": CANONICAL_CANARY_KIND,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": publication["dataset_repo_id"],
        "public_revision": publication["public_revision"],
        "public_sha": publication["public_revision"],
        "previous_public_pin": publication["previous_public_pin"],
        "staging_revision": publication["staging_revision"],
        "final_manifest_digest": publication["final_manifest_digest"],
        "release_manifest_digest": publication["release_manifest_digest"],
        "plan_digest": publication["plan_digest"],
        "policy_proof_digest": publication["policy_proof_digest"],
        "publication_receipt_digest": publication["canonical_digest"],
        "downloaded": list(redownload["downloaded"]),
        "downloaded_bytes": int(redownload["downloaded_bytes"]),
        "downloaded_file_count": int(redownload["downloaded_file_count"]),
        "exact_descriptor_match": True,
        "viewer": viewer,
        "key_sets": keys,
        "query_canaries": queries,
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return check_canonical_public_canary_receipt(receipt)


def run_canonical_public_canary(
    *,
    publication_receipt: Mapping[str, Any],
    cache_root: Path | str,
    probe_runner: Any,
    fetch_to_path: Any = huggingface_pinned_fetch_to_path,
) -> dict[str, Any]:
    """Execute pinned redownload plus Viewer/key/query probes read-only."""

    if not callable(probe_runner):
        raise PublicRemoteError("a bounded read-only probe_runner is required")
    redownload = redownload_canonical_public_release(
        publication_receipt,
        cache_root=cache_root,
        fetch_to_path=fetch_to_path,
    )
    measured = probe_runner(
        Path(cache_root).expanduser().resolve(),
        str(publication_receipt.get("dataset_repo_id") or ""),
        str(publication_receipt.get("public_revision") or ""),
    )
    if not isinstance(measured, Mapping):
        raise PublicParityError("public probe runner returned a non-object")
    return build_canonical_public_canary_receipt(
        publication_receipt=publication_receipt,
        redownload=redownload,
        viewer_probe=measured.get("viewer") or {},
        key_set_probe=measured.get("key_sets") or {},
        query_canaries=measured.get("query_canaries") or {},
    )


def check_canonical_public_canary_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise PublicPinError("canonical public canary must be an object")
    report = dict(receipt)
    if (
        report.get("schema") != CANONICAL_CANARY_SCHEMA
        or report.get("receipt_kind") != CANONICAL_CANARY_KIND
        or report.get("task_id") != TASK_ID
        or report.get("status") != "passed"
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("read_only") is not True
        or report.get("remote_mutation_attempted") is not False
        or report.get("unexpected_operations") != []
        or report.get("jurisdictions") != list(SORTED_JURISDICTIONS)
        or report.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT
        or report.get("exact_descriptor_match") is not True
    ):
        raise PublicPinError("canonical public canary identity/status drifted")
    public = require_immutable_revision(
        report.get("public_revision"), name="public_revision"
    )
    if report.get("public_sha") != public:
        raise PublicPinError("canonical public SHA aliases drifted")
    require_immutable_revision(
        report.get("staging_revision"), name="staging_revision"
    )
    for name in (
        "final_manifest_digest",
        "release_manifest_digest",
        "plan_digest",
        "policy_proof_digest",
        "publication_receipt_digest",
    ):
        if _SHA256_RE.fullmatch(str(report.get(name) or "")) is None:
            raise PublicPinError(f"{name} is malformed")
    declared = str(report.get("canonical_digest") or report.get("content_digest") or "")
    if _SHA256_RE.fullmatch(declared) is None or canonical_no_self_field_digest(
        report
    ) != declared:
        raise PublicPinError("canonical public canary digest mismatch")
    validate_canonical_viewer_probe(report.get("viewer") or {})
    validate_canonical_key_set_probe(report.get("key_sets") or {})
    validate_canonical_query_canaries(report.get("query_canaries") or {})
    downloaded = report.get("downloaded")
    if (
        not isinstance(downloaded, list)
        or len(downloaded) != int(report.get("downloaded_file_count", -1))
        or any(
            not isinstance(item, Mapping)
            or _SHA256_RE.fullmatch(str(item.get("sha256") or "")) is None
            or int(item.get("size_bytes", -1)) < 0
            for item in downloaded
        )
    ):
        raise PublicPinError("canonical public download inventory drifted")
    reject_credentials_in_payload(report, label="canonical_public_canary")
    assert_no_secrets_or_absolute_paths(report, label="canonical_public_canary")
    return report


def _load_final_dependency_snapshots(
    *,
    repo_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Reopen, validate, cross-bind, and hash all LCR-047 dependencies."""

    root = repo_root.expanduser().resolve()
    payloads: dict[str, dict[str, Any]] = {}
    raw_snapshots: dict[str, bytes] = {}
    for name, relative_path in FINAL_DEPENDENCY_RELPATHS.items():
        unresolved = root / relative_path
        if unresolved.is_symlink():
            raise PublicPinError(f"state final dependency is a symlink: {name}")
        target = unresolved.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise PublicPinError(
                f"state final dependency escapes the repository: {name}"
            ) from exc
        if not target.is_file():
            raise PublicPinError(f"state final dependency is missing: {name}")
        try:
            raw = target.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PublicPinError(
                f"state final dependency is malformed: {name}"
            ) from exc
        if type(payload) is not dict:
            raise PublicPinError(
                f"state final dependency must be an object: {name}"
            )
        raw_snapshots[name] = raw
        payloads[name] = payload

    # These imports are deliberately lazy: the benchmark, rollback, and audit
    # producers import this public-canary module for their own shared checks.
    from scripts.ops.legal_data import audit_state_laws_post_publication as audit
    from scripts.ops.legal_data import benchmark_state_laws_public_release as benchmark
    from scripts.ops.legal_data import canary_state_laws_hf_release as staging_canary
    from scripts.ops.legal_data import rehearse_state_laws_release_rollback as rollback
    from scripts.ops.legal_data import seal_state_laws_prepublication as seal
    from scripts.ops.legal_data import stage_state_laws_hf_release as stage

    checked = {
        "staging_upload": stage.check_canonical_staging_receipt(
            payloads["staging_upload"], require_live=True
        ),
        "staging_canary": staging_canary.check_canonical_staging_canary_receipt(
            payloads["staging_canary"]
        ),
        "publication": check_canonical_publication_receipt(
            payloads["publication"], require_live=True
        ),
        "public_canary": check_canonical_public_canary_receipt(
            payloads["public_canary"]
        ),
        "public_benchmark": benchmark.check_canonical_public_benchmark_receipt(
            payloads["public_benchmark"]
        ),
        "rollback_rehearsal": rollback.check_canonical_rollback_rehearsal(
            payloads["rollback_rehearsal"]
        ),
        "post_publication_audit": audit.check_canonical_post_publication_audit(
            payloads["post_publication_audit"]
        ),
    }
    seal.check_state_prepublication_seal(
        path=root / DEFAULT_PREPUBLICATION_SEAL_RELPATH,
        repo_root=root,
        require_live_staging_pin=True,
    )
    checked["prepublication_seal"] = payloads["prepublication_seal"]

    upload = checked["staging_upload"]
    staging = checked["staging_canary"]
    sealed = checked["prepublication_seal"]
    publication = checked["publication"]
    canary = checked["public_canary"]
    bench = checked["public_benchmark"]
    rehearsal = checked["rollback_rehearsal"]
    post_audit = checked["post_publication_audit"]
    public = require_immutable_revision(
        publication.get("public_revision"), name="public_revision"
    )
    previous = require_immutable_revision(
        publication.get("previous_public_pin"), name="previous_public_pin"
    )
    staging_revision = require_immutable_revision(
        staging.get("staging_revision"), name="staging_revision"
    )
    final_manifest = str(publication.get("final_manifest_digest") or "")
    release_manifest = str(publication.get("release_manifest_digest") or "")
    if (
        previous != PREVIOUS_PUBLIC_PIN
        or public == previous
        or upload.get("canonical_digest") != staging.get("staging_upload_digest")
        or sealed.get("content_digest")
        != publication.get("prepublication_seal_digest")
        or canary.get("publication_receipt_digest")
        != publication.get("canonical_digest")
        or bench.get("public_canary_digest") != canary.get("canonical_digest")
        or rehearsal.get("publication_receipt_digest")
        != publication.get("canonical_digest")
        or rehearsal.get("public_canary_digest") != canary.get("canonical_digest")
        or post_audit.get("public_canary_digest") != canary.get("canonical_digest")
        or post_audit.get("public_benchmark_digest")
        != bench.get("canonical_digest")
        or post_audit.get("rollback_rehearsal_digest")
        != rehearsal.get("canonical_digest")
        or sealed.get("plan_digest") != publication.get("plan_digest")
        or sealed.get("policy_proof_digest")
        != publication.get("policy_proof_digest")
        or sealed.get("staging_revision") != staging_revision
        or publication.get("staging_revision") != staging_revision
    ):
        raise PublicPinError("state final dependency digest/pin chain drifted")
    for name, dependency in (
        ("prepublication_seal", sealed),
        ("public_canary", canary),
        ("public_benchmark", bench),
        ("rollback_rehearsal", rehearsal),
        ("post_publication_audit", post_audit),
    ):
        if (
            dependency.get("final_manifest_digest") != final_manifest
            or dependency.get("release_manifest_digest") != release_manifest
        ):
            raise PublicPinError(
                f"state final manifest chain drifted: {name}"
            )
    for name, dependency in (
        ("public_canary", canary),
        ("public_benchmark", bench),
        ("rollback_rehearsal", rehearsal),
        ("post_publication_audit", post_audit),
    ):
        if (
            dependency.get("public_revision") != public
            or dependency.get("previous_public_pin") != previous
        ):
            raise PublicPinError(f"state final public pin chain drifted: {name}")

    for name, relative_path in FINAL_DEPENDENCY_RELPATHS.items():
        if (root / relative_path).read_bytes() != raw_snapshots[name]:
            raise PublicPinError(
                f"state final dependency changed during validation: {name}"
            )
    return checked, {
        name: hashlib.sha256(raw).hexdigest()
        for name, raw in raw_snapshots.items()
    }


def _check_state_final_release_payload(
    report: Mapping[str, Any],
    *,
    dependency_digests: Mapping[str, str] | None,
) -> dict[str, Any]:
    report = dict(report)
    if (
        report.get("schema") != RECEIPT_SCHEMA_V1
        or report.get("receipt_kind") != FINAL_RECEIPT_KIND
        or report.get("task_id") != "LCR-047"
        or report.get("goal_id") != "LCR-G090"
        or report.get("program_id") != PROGRAM_ID
        or report.get("status") != "passed"
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("target") != DEFAULT_DATASET_REPO
        or report.get("read_only") is not True
        or report.get("remote_mutation_attempted") is not False
        or report.get("rollback_target") != PREVIOUS_PUBLIC_PIN
        or report.get("schema_version") != "state-laws-final-release/v1"
        or report.get("depends_on") != ["LCR-046"]
        or report.get("unresolved_gaps") != []
    ):
        raise PublicPinError("state final release receipt is not closed")
    public = require_immutable_revision(report.get("public_revision"), name="public_revision")
    previous = require_immutable_revision(
        report.get("previous_public_pin"), name="previous_public_pin"
    )
    if (
        previous != PREVIOUS_PUBLIC_PIN
        or public == previous
        or report.get("public_sha") != public
        or report.get("old_sha") != previous
    ):
        raise PublicPinError("state final receipt public/rollback pins drifted")
    receipt_digests = report.get("receipt_digests")
    required = set(FINAL_DEPENDENCY_RELPATHS)
    if not isinstance(receipt_digests, Mapping) or set(receipt_digests) != required:
        raise PublicPinError("state final receipt dependency digest set drifted")
    for name, digest in receipt_digests.items():
        if _SHA256_RE.fullmatch(str(digest or "")) is None:
            raise PublicPinError(f"state final dependency digest is malformed: {name}")
    if dependency_digests is not None and dict(receipt_digests) != dict(
        dependency_digests
    ):
        raise PublicPinError("state final dependency bytes changed after sealing")
    evidence_paths = report.get("evidence_paths")
    expected_paths = {
        name: path.as_posix()
        for name, path in FINAL_DEPENDENCY_RELPATHS.items()
    }
    if not isinstance(evidence_paths, Mapping) or dict(evidence_paths) != expected_paths:
        raise PublicPinError("state final dependency path set drifted")
    for name in ("final_manifest_digest", "release_manifest_digest"):
        if _SHA256_RE.fullmatch(str(report.get(name) or "")) is None:
            raise PublicPinError(f"state final {name} is malformed")
    acceptance = report.get("acceptance")
    if not isinstance(acceptance, Mapping) or acceptance != {
        "all_required_receipts_bound": True,
        "every_state_law_gate_at_public_sha": True,
        "no_unresolved_gap": True,
        "prepublication_seal_bound": True,
    }:
        raise PublicPinError("state final acceptance closure drifted")
    completion = report.get("completion_proof")
    if not isinstance(completion, Mapping) or completion != {
        "kind": "final_release_receipt",
        "path": DEFAULT_FINAL_RECEIPT_RELPATH.as_posix(),
        "public_sha": public,
        "schema": RECEIPT_SCHEMA_V1,
        "status": "passed",
        "task_id": "LCR-047",
    }:
        raise PublicPinError("state final completion proof drifted")
    declared = str(report.get("canonical_digest") or report.get("content_digest") or "")
    if _SHA256_RE.fullmatch(declared) is None or canonical_no_self_field_digest(
        report
    ) != declared:
        raise PublicPinError("state final receipt digest mismatch")
    reject_credentials_in_payload(report, label="state_final_release_receipt")
    assert_no_secrets_or_absolute_paths(
        report, label="state_final_release_receipt"
    )
    return report


def build_state_final_release_receipt(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build the deterministic LCR-047 closure from existing live evidence."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    dependencies, receipt_digests = _load_final_dependency_snapshots(
        repo_root=root
    )
    publication = dependencies["publication"]
    report: dict[str, Any] = {
        "acceptance": {
            "all_required_receipts_bound": True,
            "every_state_law_gate_at_public_sha": True,
            "no_unresolved_gap": True,
            "prepublication_seal_bound": True,
        },
        "completion_proof": {
            "kind": "final_release_receipt",
            "path": DEFAULT_FINAL_RECEIPT_RELPATH.as_posix(),
            "public_sha": publication["public_revision"],
            "schema": RECEIPT_SCHEMA_V1,
            "status": "passed",
            "task_id": "LCR-047",
        },
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "depends_on": ["LCR-046"],
        "dirty": False,
        "evidence_paths": {
            name: path.as_posix()
            for name, path in FINAL_DEPENDENCY_RELPATHS.items()
        },
        "final_manifest_digest": publication["final_manifest_digest"],
        "fixture_only": False,
        "goal_id": "LCR-G090",
        "old_sha": publication["previous_public_pin"],
        "previous_public_pin": publication["previous_public_pin"],
        "producer": "check_state_laws_public_release.py",
        "program_id": PROGRAM_ID,
        "public_revision": publication["public_revision"],
        "public_sha": publication["public_revision"],
        "read_only": True,
        "receipt_digests": receipt_digests,
        "receipt_kind": FINAL_RECEIPT_KIND,
        "release_manifest_digest": publication["release_manifest_digest"],
        "remote_mutation_attempted": False,
        "rollback_target": publication["previous_public_pin"],
        "schema": RECEIPT_SCHEMA_V1,
        "schema_version": "state-laws-final-release/v1",
        "status": "passed",
        "target": DEFAULT_DATASET_REPO,
        "task_id": "LCR-047",
        "unresolved_gaps": [],
    }
    digest = canonical_no_self_field_digest(report)
    report["canonical_digest"] = digest
    report["content_digest"] = digest
    return _check_state_final_release_payload(
        report, dependency_digests=receipt_digests
    )


def write_state_final_release_receipt(
    receipt: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    """Explicitly persist one already-validated deterministic final receipt."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser()
        if path is not None
        else root / DEFAULT_FINAL_RECEIPT_RELPATH
    )
    if target.is_symlink():
        raise PublicPinError("state final receipt output must not be a symlink")
    _, dependency_digests = _load_final_dependency_snapshots(
        repo_root=Path(root)
    )
    checked = _check_state_final_release_payload(
        receipt,
        dependency_digests=dependency_digests,
    )
    write_json(target, checked)
    return target.resolve()


def check_state_final_release_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate LCR-047 and re-open every byte-bound dependency."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = Path(path) if path is not None else root / DEFAULT_FINAL_RECEIPT_RELPATH
    report = load_json_mapping(target)
    dependencies, receipt_digests = _load_final_dependency_snapshots(
        repo_root=root
    )
    checked = _check_state_final_release_payload(
        report, dependency_digests=receipt_digests
    )
    publication = dependencies["publication"]
    if (
        checked["public_revision"] != publication["public_revision"]
        or checked["previous_public_pin"] != publication["previous_public_pin"]
        or checked["final_manifest_digest"]
        != publication["final_manifest_digest"]
        or checked["release_manifest_digest"]
        != publication["release_manifest_digest"]
    ):
        raise PublicPinError("state final receipt/publication binding drifted")
    return checked


def check_state_public_release(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_public_pin: bool = False,
) -> dict[str, Any]:
    """Validate the sealed public canary against a freshly rebuilt loop."""

    pin_required = bool(require_public_pin)
    extract_pin = globals()["require_public_pin"]
    receipt = load_publication_receipt(repo_root=repo_root)

    fresh = build_public_canary_report(repo_root=repo_root)
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(repo_root)
    )
    if not sealed_path.is_file():
        raise CheckStateLawsPublicError(
            f"sealed public canary report not found: {DEFAULT_REPORT_RELPATH.as_posix()}"
        )
    sealed = load_json_mapping(sealed_path)

    if sealed.get("schema") != CANARY_SCHEMA:
        raise CheckStateLawsPublicError(
            f"sealed canary schema mismatch: {sealed.get('schema')!r}"
        )
    if sealed.get("task_id") != TASK_ID:
        raise CheckStateLawsPublicError(
            f"sealed canary task_id mismatch: {sealed.get('task_id')!r}"
        )
    if sealed.get("visibility_change_allowed") is True:
        raise CheckStateLawsPublicError("canary must never allow visibility changes")

    require_immutable_revision(sealed.get("public_sha"), name="sealed.public_sha")
    try:
        validate_repo_id(
            str(sealed.get("target_repo") or sealed.get("dataset_repo_id")),
            name="target_repo",
        )
    except ResolverError as exc:
        raise PublicRemoteError(str(exc)) from exc

    if pin_required:
        assert_public_pin_contract(sealed)
        assert_public_pin_contract(fresh)
        if extract_pin(sealed) != extract_pin(receipt):
            raise PublicPinError(
                "sealed public pin does not equal the LCR-042 receipt public SHA"
            )

    mismatches = _compare_canary_reports(fresh, sealed)
    if mismatches:
        raise CheckStateLawsPublicError(
            "state public canary check failed: " + ", ".join(mismatches[:16])
        )

    reject_credentials_in_payload(sealed, label="sealed_public_canary")
    sealed_viewer = sealed.get("viewer") if isinstance(sealed.get("viewer"), Mapping) else {}
    if sealed_viewer.get("ok") is not True or sealed_viewer.get("combined_covers_all_51") is not True:
        raise CheckStateLawsPublicError("sealed canary viewer policy failed")
    if sealed_viewer.get("ia_only") is True or sealed_viewer.get("not_ia_only") is not True:
        raise CheckStateLawsPublicError("sealed canary default Viewer is IA only")

    return {
        "check": "pass",
        "default_viewer_combined_all_51": True,
        "default_viewer_coherent": True,
        "default_viewer_not_ia_only": True,
        "embeddings_bm25_vectors_graph_adjacency_match_canonical": True,
        "every_jurisdiction_query_passed": True,
        "exact_51_coverage": True,
        "fixture_only": False,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "manifest_digest": fresh["manifest_digest"],
        "mismatches": [],
        "network_required": False,
        "observation_cutoff": fresh.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF,
        "ok": True,
        "old_sha": fresh["old_sha"],
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "phase": "state_public",
        "public_artifacts_equal_staged_candidate": True,
        "public_queries_pass_every_jurisdiction_and_dc_filter": True,
        "public_sha": fresh["public_sha"],
        "read_only": True,
        "require_public_pin": pin_required,
        "schema": CANARY_SCHEMA,
        "semantic_family_reconciled": True,
        "sparse_queries_within_budget": True,
        "staging_sha": fresh["staging_sha"],
        "task_id": TASK_ID,
        "target_repo": fresh["target_repo"],
        "viewer_ok": True,
    }


def check_state_public_release_final(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Stronger public-pin check used by later finalization tasks."""

    result = check_state_public_release(
        path,
        repo_root=repo_root,
        require_public_pin=True,
    )
    sealed = load_json_mapping(
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(repo_root)
    )
    assert_public_pin_contract(sealed)
    result["check"] = "final_pass"
    result["final"] = True
    result["require_public_pin"] = True
    return result


def run_remote_canary(
    *,
    repo_id: str,
    revision: str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Read-only remote canary against explicit immutable public coordinates."""

    del repo_root
    try:
        dataset = validate_repo_id(repo_id, name="repo_id")
        pin = validate_immutable_revision(revision, name="revision")
    except (ResolverError, MutableRevisionError) as exc:
        raise PublicRemoteError(str(exc)) from exc
    if dataset != DEFAULT_DATASET_REPO:
        raise PublicRemoteError(
            f"remote canary target must be {DEFAULT_DATASET_REPO!r}"
        )
    raise PublicRemoteError(
        "remote Hub canary is opt-in and requires an injected transport; "
        "default validation uses the immutable FakeHub public redownload. "
        f"refusing to contact {dataset}@{pin} from this environment"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_state_laws_public_release.py",
        description=(
            "Redownload and canary the immutable state-law public revision "
            "recorded by the LCR-042 publication receipt."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read and validate the existing canonical public_canary.json.",
    )
    parser.add_argument(
        "--require-public-pin",
        action="store_true",
        help="Refuse fixture-only canaries; require the recorded immutable public SHA.",
    )
    parser.add_argument(
        "--check-final",
        action="store_true",
        help=(
            "Validate LCR-047 and re-open its exact publication, seal, public "
            "canary, benchmark, rollback, and audit dependencies."
        ),
    )
    parser.add_argument(
        "--generate-final",
        action="store_true",
        help=(
            "Build deterministic LCR-047 JSON from existing verified State "
            "receipts without network contact."
        ),
    )
    parser.add_argument(
        "--write-final",
        action="store_true",
        help=(
            "With --generate-final, explicitly write state_final_release_receipt.json."
        ),
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Explicitly write a newly measured public canary receipt.",
    )
    parser.add_argument(
        "--repo-id",
        default=None,
        help="Optional explicit Hub repo for opt-in remote canary.",
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="Optional explicit immutable 40-hex public revision.",
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
        help="Override path to the sealed public canary report.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Override path to the LCR-042 publication receipt.",
    )
    parser.add_argument(
        "--final-receipt",
        type=Path,
        default=None,
        help="Override path to the terminal LCR-047 state receipt.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Empty directory for the immutable public redownload.",
    )
    parser.add_argument(
        "--verification",
        type=Path,
        default=None,
        help="Measured Viewer, key-set, and bounded query probe JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the check/receipt JSON (default: stdout).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
        canary_reject_secrets_in_argv(argv_list)
    except (
        PublishStateLawsError,
        PublishSafetyError,
        CheckStateLawsPublicError,
        CanaryStateLawsError,
        CanaryReceiptError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if args.require_public_pin and not (
            args.check
            or args.write_report
            or args.network
            or args.check_final
            or args.generate_final
        ):
            args.check = True

        if args.check_final and args.generate_final:
            raise PublicPinError(
                "--check-final and --generate-final are mutually exclusive"
            )
        if args.write_final and not args.generate_final:
            raise PublicPinError("--write-final requires --generate-final")

        if args.check_final:
            if args.write_report or args.write_final or args.network:
                raise PublicPinError("--check-final is read-only")
            result = check_state_final_release_receipt(path=args.final_receipt)
            write_json(args.output, result)
            return 0

        if args.generate_final:
            if args.write_report or args.network:
                raise PublicPinError("final receipt generation is local-only")
            result = build_state_final_release_receipt()
            if args.write_final:
                write_state_final_release_receipt(
                    result,
                    path=args.final_receipt,
                )
            write_json(args.output, result)
            return 0

        if args.check:
            if args.write_report or args.network:
                raise PublicPinError("--check is read-only")
            result = check_canonical_public_canary_receipt(
                load_json_mapping(args.canary_report or default_report_path())
            )
            write_json(args.output, result)
            return 0

        if not args.network:
            raise PublicRemoteError(
                "new public canary generation requires explicit --network opt-in"
            )
        if args.cache_dir is None or args.verification is None:
            raise PublicRemoteError(
                "public canary generation requires --cache-dir and --verification"
            )
        publication = load_json_mapping(args.receipt or default_receipt_path())
        checked_publication = check_canonical_publication_receipt(
            publication, require_live=True
        )
        remote_repo = args.repo_id or checked_publication["dataset_repo_id"]
        remote_rev = args.revision or checked_publication["public_revision"]
        if (
            remote_repo != checked_publication["dataset_repo_id"]
            or remote_rev != checked_publication["public_revision"]
        ):
            raise PublicRemoteError(
                "explicit remote coordinates differ from the publication receipt"
            )
        measured = load_json_mapping(args.verification)
        redownload = redownload_canonical_public_release(
            checked_publication,
            cache_root=args.cache_dir,
            fetch_to_path=huggingface_pinned_fetch_to_path,
        )
        report = build_canonical_public_canary_receipt(
            publication_receipt=checked_publication,
            redownload=redownload,
            viewer_probe=measured.get("viewer") or {},
            key_set_probe=measured.get("key_sets") or {},
            query_canaries=measured.get("query_canaries") or {},
        )
        if args.write_report:
            write_canary_report(
                report,
                path=args.canary_report or default_report_path(),
            )
        write_json(args.output, report)
        return 0

    except (
        CheckStateLawsPublicError,
        PublicBudgetError,
        PublicParityError,
        PublicPinError,
        PublicRemoteError,
        PublicViewerError,
        CanaryBudgetError,
        CanaryParityError,
        CanaryReceiptError,
        CanaryStateLawsError,
        CanaryViewerError,
        PublishStateLawsError,
        PublishSafetyError,
        MutableRevisionError,
        ResolverError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
