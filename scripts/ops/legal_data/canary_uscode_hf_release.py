#!/usr/bin/env python3
"""Pinned staged-remote canary and Dataset Viewer checks for US Code (USCIR-036).

Default mode is **offline fixture canary** (credential-free, no Hub contact):

1. Materialize a miniature descriptor-complete release from the sealed E2E recipe.
2. Redownload control indexes and selected shards through the immutable resolver
   (fake Hub / local root transport).
3. Verify Dataset Viewer configurations are schema-coherent and recovery never
   contaminates the default config.
4. Run sparse BM25 queries twice and assert cache/offline parity + fetch traces.
5. Record an immutable revision pin and credential-safe fetch trace.

Opt-in remote mode requires **explicit staging coordinates**
(``--repo-id`` + immutable 40-hex ``--revision``) and never infers a mutable
branch such as ``main`` / ``latest``. Network contact is read-only and bounded.

Validation gate (no network)::

    python scripts/ops/legal_data/canary_uscode_hf_release.py --fixture-only --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_SOURCE_REVISION,
    RECOVERY_CONFIG_NAME,
    UscodeHFReleaseConfigError,
    UscodeHFReleaseError,
    UscodeHFReleaseSafetyError,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
)
from ipfs_datasets_py.processors.legal_data.uscode_query import (  # noqa: E402
    UscodeQueryClient,
    UscodeQueryError,
    UscodeQueryInputError,
    query_replay_fingerprint,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import QueryLimits  # noqa: E402
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    HuggingFaceHubTransport,
    ImmutableHubResolver,
    LocalRootTransport,
    MappingTransport,
    MutableRevisionError,
    ResolverError,
    build_descriptor_for_bytes,
    validate_immutable_revision,
    validate_repo_id,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (  # noqa: E402
    canonical_json_dumps,
    digest_mapping,
)

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as _pyarrow_exc:  # pragma: no cover - hard dependency in this repo
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]
    _PYARROW_IMPORT_ERROR = _pyarrow_exc
else:
    _PYARROW_IMPORT_ERROR = None

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-036"
GOAL_ID: Final = "USCIR-G090"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "canary_uscode_hf_release.py"
CODE_VERSION: Final = "1"

CANARY_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-remote-canary@1"
RECEIPT_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-canary-receipt@1"

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_STAGING_REVISION: Final = DEFAULT_SOURCE_REVISION
DEFAULT_STAGING_BRANCH: Final = "stage/uscode-sparse-graphrag-v2"
DEFAULT_RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

DEFAULT_CANARY_FIXTURE_RELPATH: Final = Path(
    "tests/fixtures/legal_ir/uscode_remote_canary.json"
)
DEFAULT_E2E_RECIPE_RELPATH: Final = Path(
    "tests/fixtures/legal_ir/uscode_e2e_release/recipe.json"
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "USCODE_STAGING_AUTHORIZATION",
)

# Opt-in remote env coordinates (explicit; never inferred from mutable refs).
REMOTE_REPO_ENV: Final = "USCODE_CANARY_REPO_ID"
REMOTE_REVISION_ENV: Final = "USCODE_CANARY_REVISION"
REMOTE_ENABLE_ENV: Final = "USCODE_CANARY_REMOTE"

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_MUTABLE_REFS: Final = frozenset(
    {
        "main",
        "master",
        "latest",
        "head",
        "dev",
        "develop",
        "production",
        "prod",
        "live",
        "staging",
        "canary",
        "default",
        "current",
    }
)


class CanaryUscodeError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class CanaryBudgetError(CanaryUscodeError):
    """Raised when redownload or query budgets are exceeded."""


class CanaryViewerError(CanaryUscodeError):
    """Raised when Dataset Viewer configs are invalid."""


class CanaryParityError(CanaryUscodeError):
    """Raised when second-run cache/offline parity fails."""


class CanaryRemoteError(CanaryUscodeError):
    """Raised when remote coordinates are missing or mutable."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_canary_fixture_path(repo_root: Path | str | None = None) -> Path:
    """Return the repository-relative sealed remote-canary fixture path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_CANARY_FIXTURE_RELPATH).resolve()


def default_e2e_recipe_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_E2E_RECIPE_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise CanaryUscodeError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CanaryUscodeError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CanaryUscodeError(f"JSON root must be an object: {target}")
    return dict(payload)


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Credential / safety guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens or secret-like values appear in public surfaces."""

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
        raise CanaryUscodeError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    """Refuse secrets passed on the command line (credentials are env-only)."""
    lowered = " ".join(str(a) for a in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "api_key=",
        "huggingface_token=",
    )
    for needle in needles:
        if needle in lowered:
            raise CanaryUscodeError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )


def require_immutable_staging_revision(value: Any, *, name: str = "revision") -> str:
    """Require an immutable 40-hex Hub commit SHA; never accept mutable refs."""
    if not isinstance(value, str) or not value.strip():
        raise CanaryRemoteError(
            f"{name} must be an explicit immutable 40-hex staging revision"
        )
    text = value.strip()
    if text.casefold() in _MUTABLE_REFS or text.casefold().startswith("refs/"):
        raise CanaryRemoteError(
            f"{name} must never be a mutable ref ({text!r}); pin a 40-hex SHA"
        )
    try:
        return validate_immutable_revision(text, name=name)
    except MutableRevisionError as exc:
        raise CanaryRemoteError(str(exc)) from exc


def require_repo_id(value: Any, *, name: str = "repo_id") -> str:
    try:
        return validate_repo_id(value, name=name)
    except ResolverError as exc:
        raise CanaryRemoteError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Offline release materializer (compact e2e recipe → queryable local root)
# ---------------------------------------------------------------------------


def _require_pyarrow() -> None:
    if pa is None or pq is None:
        raise CanaryUscodeError(
            "pyarrow is required for canary release materialization"
        ) from _PYARROW_IMPORT_ERROR


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> bytes:
    _require_pyarrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([dict(row) for row in rows])
    pq.write_table(table, path, compression="zstd")
    return path.read_bytes()


def _desc(path: Path, root: Path, *, row_count: int) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    content = path.read_bytes()
    return build_descriptor_for_bytes(
        relative,
        content,
        row_count=row_count,
        media_type="application/vnd.apache.parquet",
        schema_id="hf-graphrag-release/v1",
    ).to_dict()


def materialize_canary_release(
    root: Path,
    recipe: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Materialize a descriptor-complete offline release for canary checks."""

    if recipe is None:
        recipe = load_json_mapping(default_e2e_recipe_path(repo_root))
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    families = recipe["families"]
    routing = recipe["routing"]
    model = recipe["model"]
    bm25_cfg = recipe["bm25"]

    postings = families["bm25_postings"]
    post_descs: dict[str, dict[str, Any]] = {}
    for part_name, rows in postings.items():
        path = root / f"data/bm25/postings/{part_name}.parquet"
        _write_parquet(path, rows)
        post_descs[part_name] = _desc(path, root, row_count=len(rows))

    keyword_meta = []
    for entry in routing["bm25_keyword_shards"]:
        part = Path(entry["relative_path"]).stem
        desc = post_descs[part]
        keyword_meta.append(
            {**desc, **{k: v for k, v in entry.items() if k != "relative_path"}}
        )
    keyword_path = root / "indexes/bm25_keyword_shards.parquet"
    _write_parquet(keyword_path, keyword_meta)
    keyword_desc = _desc(keyword_path, root, row_count=len(keyword_meta))

    corpus_rows = list(families["corpus"])
    corpus_path = root / "data/corpus/part-000000.parquet"
    _write_parquet(corpus_path, corpus_rows)
    corpus_desc = _desc(corpus_path, root, row_count=len(corpus_rows))
    corpus_meta = []
    for entry in routing["corpus_chunks"]:
        corpus_meta.append(
            {
                **corpus_desc,
                **{k: v for k, v in entry.items() if k != "relative_path"},
            }
        )
    corpus_index_path = root / "indexes/corpus_chunks.parquet"
    _write_parquet(corpus_index_path, corpus_meta)
    corpus_index_desc = _desc(corpus_index_path, root, row_count=len(corpus_meta))

    vec_descs: dict[str, dict[str, Any]] = {}
    for part_name, rows in families["vectors"].items():
        path = root / f"data/vectors/{part_name}.parquet"
        _write_parquet(path, rows)
        vec_descs[part_name] = _desc(path, root, row_count=len(rows))
    vector_meta = []
    for entry in routing["vector_chunks"]:
        part = Path(entry["relative_path"]).stem
        desc = vec_descs[part]
        vector_meta.append(
            {**desc, **{k: v for k, v in entry.items() if k != "relative_path"}}
        )
    vector_index_path = root / "indexes/vector_chunks.parquet"
    _write_parquet(vector_index_path, vector_meta)
    vector_index_desc = _desc(vector_index_path, root, row_count=len(vector_meta))

    adj_rows = list(families["graph_adjacency_out"])
    adj_path = root / "data/graph/adjacency/out/part-000000.parquet"
    _write_parquet(adj_path, adj_rows)
    adj_desc = _desc(adj_path, root, row_count=len(adj_rows))
    adj_meta = []
    for entry in routing["graph_out_adjacency"]:
        adj_meta.append(
            {**adj_desc, **{k: v for k, v in entry.items() if k != "relative_path"}}
        )
    adj_index_path = root / "indexes/graph_out_adjacency.parquet"
    _write_parquet(adj_index_path, adj_meta)
    adj_index_desc = _desc(adj_index_path, root, row_count=len(adj_meta))

    # Viewer control-plane files (offline validity surface).
    viewer_configs = advertised_viewer_configs()
    assert_configs_schema_coherent(viewer_configs)
    dataset_configs = {
        "configs": [cfg.to_dict() for cfg in viewer_configs],
        "default_config": DEFAULT_CONFIG_NAME,
        "schema_version": "uscode-dataset-configs/v1",
    }
    (root / "dataset_configs.json").write_bytes(
        canonical_json_dumps(dataset_configs).encode("utf-8")
    )
    readme = (
        "---\n"
        "configs:\n"
        f'- config_name: "{DEFAULT_CONFIG_NAME}"\n'
        "  data_files:\n"
        '  - split: "train"\n'
        '    path: "data/**/*.parquet"\n'
        "---\n\n"
        "# US Code Sparse GraphRAG canary fixture\n"
    )
    (root / "README.md").write_text(readme, encoding="utf-8")

    manifest = {
        "bm25": dict(bm25_cfg),
        "indexes": {
            "bm25_keyword_shards": keyword_desc,
            "corpus_chunks": corpus_index_desc,
            "graph_out_adjacency": adj_index_desc,
            "vector_chunks": vector_index_desc,
        },
        "primary_key": recipe["primary_key"],
        "release_profile": str(
            recipe.get("release_profile") or DEFAULT_RELEASE_PROFILE
        ),
        "schema_version": "hf-graphrag-release/v1",
        "vector": {
            "default_probe_centroids": 1,
            "dimension": int(model["dimension"]),
            "layout": "semantic_centroid_groups",
            "max_shards_per_centroid": 1,
            "model_id": model["model_id"],
            "model_name": model["model_id"],
            "model_revision": model["model_revision"],
            "normalization": model["normalization"],
            "vector_space_id": model["vector_space_id"],
        },
    }
    (root / "manifest.json").write_bytes(
        canonical_json_dumps(manifest).encode("utf-8")
    )
    return manifest


def release_file_bytes(root: Path) -> dict[str, bytes]:
    """Map relative path → bytes for every regular file under *root*."""
    inventory: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        inventory[rel] = path.read_bytes()
    return inventory


# ---------------------------------------------------------------------------
# Fixture policy surface
# ---------------------------------------------------------------------------


def build_fixture_canary_recipe(
    *,
    target_repo: str = DEFAULT_DATASET_REPO,
    staging_revision: str = DEFAULT_STAGING_REVISION,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
) -> dict[str, Any]:
    """Build the deterministic offline canary policy surface (sealed recipe)."""

    revision = require_immutable_staging_revision(
        staging_revision, name="staging_revision"
    )
    repo = require_repo_id(target_repo, name="target_repo")
    configs = advertised_viewer_configs()
    assert_configs_schema_coherent(configs)
    config_names = [cfg.config_name for cfg in configs]

    recipe: dict[str, Any] = {
        "acceptance": {
            "bounded_downloads": True,
            "cache_offline_parity": True,
            "fixture_canary_offline": True,
            "immutable_revision_required": True,
            "never_infer_mutable_revision": True,
            "read_only": True,
            "remote_opt_in_only": True,
            "viewer_configs_valid": True,
        },
        "budgets": {
            "max_bytes": 5_000_000,
            "max_control_index_bytes": 2_000_000,
            "max_selected_shard_bytes": 3_000_000,
            "max_shards": 16,
            "max_query_bytes": 4_000_000,
            "max_query_shards": 12,
        },
        "code_version": CODE_VERSION,
        "control_indexes": [
            "manifest.json",
            "indexes/bm25_keyword_shards.parquet",
            "indexes/corpus_chunks.parquet",
            "indexes/vector_chunks.parquet",
            "indexes/graph_out_adjacency.parquet",
        ],
        "default_config": DEFAULT_CONFIG_NAME,
        "digest_sealed": False,
        "fixture_id": "uscode-remote-canary-v1",
        "generators": {
            "canary": "run_fixture_canary()",
            "check": "check_canary_fixture()",
            "release_recipe": str(DEFAULT_E2E_RECIPE_RELPATH).replace("\\", "/"),
            "viewer": "advertised_viewer_configs()",
        },
        "goal_id": GOAL_ID,
        "network_required": False,
        "notes": (
            "Compact sealed recipe for the pinned staged-remote canary and "
            "Dataset Viewer checks (USCIR-036). Default validation is offline "
            "against a fake Hub fixture. Remote mode is opt-in and requires "
            "explicit staging coordinates (repo_id + immutable 40-hex revision). "
            "Expand via canary_uscode_hf_release.py."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "queries": [
            {
                "expected_min_results": 1,
                "expected_top_entry_cid": "entry-a",
                "id": "bm25_agency",
                "mode": "bm25",
                "query": "agency",
                "runs": 2,
                "top_k": 3,
            },
            {
                "expected_min_results": 1,
                "expected_top_entry_cid": "entry-a",
                "id": "bm25_foia",
                "mode": "bm25",
                "query": "foia",
                "runs": 2,
                "top_k": 2,
            },
        ],
        "release_point": "usc-2024-main-20240920",
        "release_profile": DEFAULT_RELEASE_PROFILE,
        "schema": CANARY_SCHEMA,
        "selected_shards": [
            "data/bm25/postings/part-000000.parquet",
            "data/corpus/part-000000.parquet",
            "data/vectors/centroid-000000-part-000000.parquet",
        ],
        "staging_branch": staging_branch,
        "staging_revision": revision,
        "target_repo": repo,
        "task_id": TASK_ID,
        "viewer": {
            "default_config": DEFAULT_CONFIG_NAME,
            "default_excludes_recovery": True,
            "default_excludes_legacy_monoliths": True,
            "exactly_one_default": True,
            "required_config_names": config_names,
            "schema_coherent": True,
        },
    }
    return recipe


def compare_canary_recipes(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    """Compare policy surfaces; ignore free-form notes."""

    mismatches: list[str] = []
    keys = (
        "schema",
        "task_id",
        "goal_id",
        "fixture_id",
        "target_repo",
        "staging_revision",
        "staging_branch",
        "release_profile",
        "default_config",
        "network_required",
        "producer",
        "program_id",
        "code_version",
    )
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(
                f"{key}: fresh={fresh.get(key)!r} sealed={sealed.get(key)!r}"
            )

    for key in ("control_indexes", "selected_shards"):
        if list(fresh.get(key) or []) != list(sealed.get(key) or []):
            mismatches.append(f"{key} mismatch")

    fresh_acc = dict(fresh.get("acceptance") or {})
    sealed_acc = dict(sealed.get("acceptance") or {})
    for key, expected in fresh_acc.items():
        if sealed_acc.get(key) != expected:
            mismatches.append(f"acceptance.{key} mismatch")

    fresh_viewer = dict(fresh.get("viewer") or {})
    sealed_viewer = dict(sealed.get("viewer") or {})
    for key in (
        "default_config",
        "default_excludes_recovery",
        "default_excludes_legacy_monoliths",
        "exactly_one_default",
        "schema_coherent",
    ):
        if fresh_viewer.get(key) != sealed_viewer.get(key):
            mismatches.append(f"viewer.{key} mismatch")
    if list(fresh_viewer.get("required_config_names") or []) != list(
        sealed_viewer.get("required_config_names") or []
    ):
        mismatches.append("viewer.required_config_names mismatch")

    fresh_budgets = dict(fresh.get("budgets") or {})
    sealed_budgets = dict(sealed.get("budgets") or {})
    for key, expected in fresh_budgets.items():
        if sealed_budgets.get(key) != expected:
            mismatches.append(f"budgets.{key} mismatch")

    fresh_queries = list(fresh.get("queries") or [])
    sealed_queries = list(sealed.get("queries") or [])
    if len(fresh_queries) != len(sealed_queries):
        mismatches.append("queries length mismatch")
    else:
        for index, (f_q, s_q) in enumerate(zip(fresh_queries, sealed_queries)):
            for field in ("id", "mode", "query", "runs", "top_k"):
                if f_q.get(field) != s_q.get(field):
                    mismatches.append(f"queries[{index}].{field} mismatch")

    return mismatches


def check_canary_fixture(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the sealed fixture against a freshly built fixture recipe."""

    fresh = build_fixture_canary_recipe()
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_canary_fixture_path(repo_root)
    )
    sealed = load_json_mapping(sealed_path)

    if sealed.get("schema") != CANARY_SCHEMA:
        raise CanaryUscodeError(
            f"sealed fixture schema mismatch: {sealed.get('schema')!r}"
        )
    if sealed.get("task_id") != TASK_ID:
        raise CanaryUscodeError(
            f"sealed fixture task_id mismatch: {sealed.get('task_id')!r}"
        )
    if sealed.get("network_required") is not False:
        raise CanaryUscodeError(
            "sealed fixture must declare network_required=false for default gate"
        )
    if sealed.get("visibility_change_allowed") is True:
        raise CanaryUscodeError("canary must never allow visibility changes")

    # Policy surface: revision must be immutable 40-hex.
    require_immutable_staging_revision(
        sealed.get("staging_revision"), name="sealed.staging_revision"
    )
    require_repo_id(sealed.get("target_repo"), name="sealed.target_repo")

    mismatches = compare_canary_recipes(fresh, sealed)
    if mismatches:
        raise CanaryUscodeError(
            "canary fixture check failed: " + "; ".join(mismatches[:12])
        )

    # Viewer surface from sealed recipe must itself be coherent.
    viewer_report = verify_viewer_configs(sealed.get("viewer") or {})
    if not viewer_report.get("ok"):
        raise CanaryViewerError(
            "sealed fixture viewer policy failed: "
            + ", ".join(viewer_report.get("errors") or [])
        )

    return {
        "ok": True,
        "path": str(DEFAULT_CANARY_FIXTURE_RELPATH).replace("\\", "/"),
        "mismatches": [],
        "schema": CANARY_SCHEMA,
        "task_id": TASK_ID,
        "target_repo": fresh["target_repo"],
        "staging_revision": fresh["staging_revision"],
        "staging_branch": fresh["staging_branch"],
        "network_required": False,
        "viewer_ok": True,
        "fixture_id": fresh["fixture_id"],
    }


# ---------------------------------------------------------------------------
# Viewer checks
# ---------------------------------------------------------------------------


def verify_viewer_configs(
    viewer_policy: Mapping[str, Any] | None = None,
    *,
    include_legacy: bool = True,
    include_recovery: bool = True,
) -> dict[str, Any]:
    """Verify advertised Dataset Viewer configs against sealed policy."""

    errors: list[str] = []
    try:
        configs = advertised_viewer_configs(
            include_legacy=include_legacy,
            include_recovery=include_recovery,
        )
        coherence = assert_configs_schema_coherent(configs)
    except (
        UscodeHFReleaseConfigError,
        UscodeHFReleaseSafetyError,
        UscodeHFReleaseError,
        ValueError,
        TypeError,
    ) as exc:
        return {
            "ok": False,
            "errors": [str(exc)],
            "config_names": [],
            "default_config": None,
            "coherence": {},
        }

    config_names = [cfg.config_name for cfg in configs]
    defaults = [cfg for cfg in configs if cfg.is_default]
    default_name = defaults[0].config_name if defaults else None

    policy = dict(viewer_policy or {})
    expected_default = str(policy.get("default_config") or DEFAULT_CONFIG_NAME)
    if default_name != expected_default:
        errors.append(
            f"default config is {default_name!r}, expected {expected_default!r}"
        )
    if policy.get("exactly_one_default", True) and len(defaults) != 1:
        errors.append(f"expected exactly one default config, found {len(defaults)}")

    required = list(policy.get("required_config_names") or config_names)
    for name in required:
        if name not in config_names:
            errors.append(f"missing required viewer config: {name}")

    if policy.get("default_excludes_recovery", True):
        for cfg in defaults:
            for entry in cfg.data_files:
                path = str(entry.get("path") or "")
                if "recovery" in path or path.startswith("recovery/"):
                    errors.append(
                        f"default config includes recovery path {path!r}"
                    )
            if cfg.is_recovery:
                errors.append("default config is marked recovery")

    if policy.get("default_excludes_legacy_monoliths", True):
        for cfg in defaults:
            for entry in cfg.data_files:
                path = str(entry.get("path") or "")
                if path.startswith("uscode_parquet/"):
                    errors.append(
                        f"default config includes legacy monolith path {path!r}"
                    )

    recovery_cfgs = [cfg for cfg in configs if cfg.is_recovery]
    if include_recovery and not recovery_cfgs:
        errors.append("recovery quarantine config missing")
    if any(cfg.config_name == RECOVERY_CONFIG_NAME and cfg.is_default for cfg in configs):
        errors.append("recovery config must never be default")

    return {
        "ok": not errors,
        "errors": errors,
        "config_names": config_names,
        "default_config": default_name,
        "coherence": dict(coherence) if isinstance(coherence, Mapping) else {},
        "config_count": len(configs),
        "recovery_isolated": all(not cfg.is_default for cfg in recovery_cfgs),
    }


def verify_release_viewer_files(root: Path) -> dict[str, Any]:
    """Validate on-disk viewer control files when present under a release root."""

    root = Path(root)
    report: dict[str, Any] = {
        "dataset_configs_present": False,
        "readme_present": False,
        "ok": True,
        "errors": [],
    }
    configs_path = root / "dataset_configs.json"
    if configs_path.is_file():
        report["dataset_configs_present"] = True
        try:
            payload = json.loads(configs_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            report["ok"] = False
            report["errors"].append(f"dataset_configs.json unreadable: {exc}")
            return report
        if not isinstance(payload, Mapping):
            report["ok"] = False
            report["errors"].append("dataset_configs.json must be an object")
            return report
        default = payload.get("default_config")
        if default != DEFAULT_CONFIG_NAME:
            report["ok"] = False
            report["errors"].append(
                f"dataset_configs default_config is {default!r}"
            )
        for cfg in payload.get("configs") or []:
            if not isinstance(cfg, Mapping):
                continue
            name = str(cfg.get("config_name") or "")
            is_default = bool(cfg.get("is_default"))
            if is_default and name != DEFAULT_CONFIG_NAME:
                report["ok"] = False
                report["errors"].append(
                    f"non-v2 default config advertised: {name!r}"
                )
            if is_default:
                for entry in cfg.get("data_files") or []:
                    if not isinstance(entry, Mapping):
                        continue
                    path = str(entry.get("path") or "")
                    if "recovery" in path:
                        report["ok"] = False
                        report["errors"].append(
                            f"default data_files includes recovery: {path!r}"
                        )
    readme = root / "README.md"
    if readme.is_file():
        report["readme_present"] = True
        text = readme.read_text(encoding="utf-8")
        if DEFAULT_CONFIG_NAME not in text:
            report["ok"] = False
            report["errors"].append("README.md missing default config name")
    return report


# ---------------------------------------------------------------------------
# Redownload + query canary core
# ---------------------------------------------------------------------------


def _budgets_from_recipe(recipe: Mapping[str, Any]) -> dict[str, int]:
    raw = dict(recipe.get("budgets") or {})
    return {
        "max_bytes": int(raw.get("max_bytes") or 5_000_000),
        "max_control_index_bytes": int(raw.get("max_control_index_bytes") or 2_000_000),
        "max_selected_shard_bytes": int(raw.get("max_selected_shard_bytes") or 3_000_000),
        "max_shards": int(raw.get("max_shards") or 16),
        "max_query_bytes": int(raw.get("max_query_bytes") or 4_000_000),
        "max_query_shards": int(raw.get("max_query_shards") or 12),
    }


def redownload_paths(
    resolver: ImmutableHubResolver,
    paths: Sequence[str],
    *,
    budget_bytes: int,
    budget_shards: int,
    label: str,
) -> dict[str, Any]:
    """Redownload listed paths with byte/shard bounds and digest verification."""

    if len(paths) > budget_shards:
        raise CanaryBudgetError(
            f"{label}: path count {len(paths)} exceeds max_shards={budget_shards}"
        )
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for rel in paths:
        artifact = resolver.resolve(str(rel))
        entry = {
            "relative_path": artifact.relative_path,
            "size_bytes": int(artifact.size_bytes),
            "sha256": artifact.sha256,
            "cache_hit": bool(artifact.cache_hit),
            "verified": bool(artifact.verified),
        }
        files.append(entry)
        total_bytes += int(artifact.size_bytes)
        if total_bytes > budget_bytes:
            raise CanaryBudgetError(
                f"{label}: total_bytes {total_bytes} exceeds budget {budget_bytes}"
            )
    return {
        "label": label,
        "file_count": len(files),
        "files": files,
        "total_bytes": total_bytes,
        "within_budget": total_bytes <= budget_bytes and len(files) <= budget_shards,
        "budget_bytes": budget_bytes,
        "budget_shards": budget_shards,
    }


def _hit_entry_cid(hit: Mapping[str, Any]) -> str:
    for key in ("entry_cid", "cid", "id"):
        value = hit.get(key)
        if value:
            return str(value)
    meta = hit.get("metadata") if isinstance(hit.get("metadata"), Mapping) else {}
    for key in ("entry_cid", "cid", "id"):
        value = meta.get(key)
        if value:
            return str(value)
    return ""


def run_sparse_queries(
    client: UscodeQueryClient,
    queries: Sequence[Mapping[str, Any]],
    *,
    max_bytes: int,
    max_shards: int,
) -> list[dict[str, Any]]:
    """Run sparse queries (each query ``runs`` times) and check cache parity."""

    receipts: list[dict[str, Any]] = []
    for spec in queries:
        mode = str(spec.get("mode") or "bm25")
        if mode != "bm25":
            raise CanaryUscodeError(
                f"canary currently supports bm25 queries only, got {mode!r}"
            )
        query_text = str(spec.get("query") or "").strip()
        if not query_text:
            raise CanaryUscodeError(f"query {spec.get('id')!r} is empty")
        top_k = int(spec.get("top_k") or 3)
        runs = int(spec.get("runs") or 2)
        if runs < 1:
            raise CanaryUscodeError("query runs must be >= 1")
        expected_min = int(spec.get("expected_min_results") or 0)
        expected_top = spec.get("expected_top_entry_cid")

        run_payloads: list[dict[str, Any]] = []
        fingerprints: list[str] = []
        for run_index in range(1, runs + 1):
            try:
                result = client.bm25_search(query_text, top_k=top_k, hydrate=True)
            except (UscodeQueryError, UscodeQueryInputError, ResolverError) as exc:
                raise CanaryUscodeError(
                    f"query {spec.get('id')!r} run {run_index} failed: {exc}"
                ) from exc
            hits = [
                dict(h) if isinstance(h, Mapping) else {"value": h}
                for h in result.results
            ]
            top_cid = _hit_entry_cid(hits[0]) if hits else ""
            if not top_cid and hits:
                # Prefer ordered_result_cids when packaged under alternate keys.
                ordered = list(result.ordered_result_cids())
                top_cid = ordered[0] if ordered else ""
            fingerprint = query_replay_fingerprint(result)
            fingerprints.append(fingerprint)
            trace = dict(result.fetch_trace or {})
            total_bytes = int(trace.get("total_file_bytes") or 0)
            file_count = int(trace.get("file_count") or len(trace.get("files") or []))
            if total_bytes > max_bytes:
                raise CanaryBudgetError(
                    f"query {spec.get('id')!r} run {run_index} "
                    f"exceeded max_query_bytes ({total_bytes} > {max_bytes})"
                )
            if file_count > max_shards:
                raise CanaryBudgetError(
                    f"query {spec.get('id')!r} run {run_index} "
                    f"exceeded max_query_shards ({file_count} > {max_shards})"
                )
            if expected_min and len(hits) < expected_min:
                raise CanaryUscodeError(
                    f"query {spec.get('id')!r} run {run_index}: "
                    f"got {len(hits)} hits, expected >= {expected_min}"
                )
            if expected_top is not None and str(expected_top):
                if not top_cid:
                    raise CanaryUscodeError(
                        f"query {spec.get('id')!r} run {run_index}: "
                        f"missing top entry_cid (expected {expected_top!r})"
                    )
                if top_cid != str(expected_top):
                    raise CanaryUscodeError(
                        f"query {spec.get('id')!r} run {run_index}: "
                        f"top entry_cid {top_cid!r} != {expected_top!r}"
                    )
            run_payloads.append(
                {
                    "run": run_index,
                    "hit_count": len(hits),
                    "top_entry_cid": top_cid,
                    "replay_fingerprint": fingerprint,
                    "fetch_trace": {
                        "cache_hits": int(trace.get("cache_hits") or 0),
                        "file_count": file_count,
                        "total_file_bytes": total_bytes,
                        "verification_state": trace.get("verification_state"),
                        "revision": trace.get("revision"),
                        "repo_id": trace.get("repo_id"),
                    },
                }
            )

        # Cache / offline parity across runs.
        if len(set(fingerprints)) != 1:
            raise CanaryParityError(
                f"query {spec.get('id')!r}: replay fingerprints diverge across runs"
            )
        cache_hits_second = (
            int(run_payloads[1]["fetch_trace"]["cache_hits"])
            if len(run_payloads) > 1
            else 0
        )
        parity_ok = len(run_payloads) == 1 or (
            run_payloads[0]["replay_fingerprint"]
            == run_payloads[-1]["replay_fingerprint"]
            and run_payloads[0]["top_entry_cid"]
            == run_payloads[-1]["top_entry_cid"]
            and run_payloads[0]["hit_count"] == run_payloads[-1]["hit_count"]
        )
        if not parity_ok:
            raise CanaryParityError(
                f"query {spec.get('id')!r}: cache/offline parity failed"
            )

        receipts.append(
            {
                "id": spec.get("id"),
                "mode": mode,
                "query": query_text,
                "top_k": top_k,
                "runs": runs,
                "parity_ok": parity_ok,
                "cache_hits_on_second_run": cache_hits_second,
                "run_receipts": run_payloads,
                "replay_fingerprint": fingerprints[0] if fingerprints else "",
            }
        )
    return receipts


def _open_query_client(
    resolver: ImmutableHubResolver,
    *,
    max_bytes: int,
    max_shards: int,
) -> UscodeQueryClient:
    return UscodeQueryClient(
        resolver,
        limits=QueryLimits(
            max_bytes=max_bytes,
            max_shards=max_shards,
            max_rows=10_000,
            max_nodes=64,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
    )


def run_canary(
    *,
    recipe: Mapping[str, Any] | None = None,
    mode: str = "fixture",
    repo_id: str | None = None,
    revision: str | None = None,
    release_root: Path | str | None = None,
    cache_dir: Path | str | None = None,
    transport: Any | None = None,
    network: bool = False,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Run the pinned canary (fixture offline or opt-in remote).

    Parameters
    ----------
    recipe:
        Canary policy recipe (defaults to sealed fixture).
    mode:
        ``fixture`` (offline fake Hub) or ``remote`` (explicit coordinates).
    repo_id / revision:
        Required for remote mode; must be owner/name + 40-hex SHA.
    release_root:
        Optional pre-materialized local release root (fixture mode).
    cache_dir:
        Optional resolver cache directory.
    transport:
        Optional injectable Hub transport (tests / fake remote).
    network:
        When True with remote mode, use :class:`HuggingFaceHubTransport`.
    """

    policy = dict(recipe or load_json_mapping(default_canary_fixture_path(repo_root)))
    if policy.get("schema") and policy.get("schema") != CANARY_SCHEMA:
        raise CanaryUscodeError(
            f"canary recipe schema mismatch: {policy.get('schema')!r}"
        )

    mode_text = str(mode or "fixture").strip().lower()
    if mode_text not in {"fixture", "remote"}:
        raise CanaryUscodeError(f"unsupported canary mode: {mode_text!r}")

    budgets = _budgets_from_recipe(policy)
    control_indexes = [str(p) for p in (policy.get("control_indexes") or [])]
    selected_shards = [str(p) for p in (policy.get("selected_shards") or [])]
    queries = list(policy.get("queries") or [])
    if not control_indexes:
        raise CanaryUscodeError("canary recipe missing control_indexes")
    if not selected_shards:
        raise CanaryUscodeError("canary recipe missing selected_shards")
    if not queries:
        raise CanaryUscodeError("canary recipe missing queries")

    # Viewer checks always run (policy + live advertised configs).
    viewer_report = verify_viewer_configs(policy.get("viewer") or {})
    if not viewer_report.get("ok"):
        raise CanaryViewerError(
            "viewer configs invalid: " + "; ".join(viewer_report.get("errors") or [])
        )

    staging_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    cache_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    network_invoked = False

    try:
        if mode_text == "fixture":
            pin_repo = require_repo_id(
                repo_id or policy.get("target_repo") or DEFAULT_DATASET_REPO
            )
            pin_revision = require_immutable_staging_revision(
                revision or policy.get("staging_revision") or DEFAULT_STAGING_REVISION
            )
            if release_root is not None:
                root = Path(release_root).expanduser().resolve()
                if not root.is_dir():
                    raise CanaryUscodeError(f"release_root is not a directory: {root}")
            else:
                staging_tmpdir = tempfile.TemporaryDirectory(prefix="uscode-canary-")
                root = Path(staging_tmpdir.name) / "release"
                materialize_canary_release(root, repo_root=repo_root)
            disk_viewer = verify_release_viewer_files(root)
            if not disk_viewer.get("ok"):
                raise CanaryViewerError(
                    "release viewer files invalid: "
                    + "; ".join(disk_viewer.get("errors") or [])
                )
            if cache_dir is None:
                cache_tmpdir = tempfile.TemporaryDirectory(prefix="uscode-canary-cache-")
                cache_path = Path(cache_tmpdir.name)
            else:
                cache_path = Path(cache_dir).expanduser().resolve()
                cache_path.mkdir(parents=True, exist_ok=True)

            if transport is None:
                # Offline fake Hub: local release root (no network contact).
                transport = LocalRootTransport(root)
            resolver = ImmutableHubResolver(
                repo_id=pin_repo,
                revision=pin_revision,
                cache_dir=cache_path,
                transport=transport,
                local_root=root
                if isinstance(transport, LocalRootTransport)
                else None,
                supported_schemas={
                    "hf-graphrag-release/v1",
                    "publicus-ir-graphrag/v2",
                },
            )
        else:
            # Remote: explicit coordinates required; never infer mutable revision.
            if not repo_id or not revision:
                raise CanaryRemoteError(
                    "remote canary requires explicit --repo-id and --revision "
                    f"(or ${REMOTE_REPO_ENV} / ${REMOTE_REVISION_ENV})"
                )
            pin_repo = require_repo_id(repo_id)
            pin_revision = require_immutable_staging_revision(revision)
            if cache_dir is None:
                cache_tmpdir = tempfile.TemporaryDirectory(prefix="uscode-canary-cache-")
                cache_path = Path(cache_tmpdir.name)
            else:
                cache_path = Path(cache_dir).expanduser().resolve()
                cache_path.mkdir(parents=True, exist_ok=True)

            if transport is not None:
                # Injected transport (tests simulate remote without network).
                resolver = ImmutableHubResolver(
                    repo_id=pin_repo,
                    revision=pin_revision,
                    cache_dir=cache_path,
                    transport=transport,
                    supported_schemas={
                        "hf-graphrag-release/v1",
                        "publicus-ir-graphrag/v2",
                    },
                )
                network_invoked = False
            elif network:
                network_invoked = True
                resolver = ImmutableHubResolver(
                    repo_id=pin_repo,
                    revision=pin_revision,
                    cache_dir=cache_path,
                    transport=HuggingFaceHubTransport(),
                    supported_schemas={
                        "hf-graphrag-release/v1",
                        "publicus-ir-graphrag/v2",
                        "uscode-sparse-graphrag-release-schema-v2",
                    },
                )
            else:
                raise CanaryRemoteError(
                    "remote canary without --network requires an injected "
                    "transport (use fixture mode or pass a fake Hub transport)"
                )
            disk_viewer = {"ok": True, "dataset_configs_present": False}

        # 1) Redownload control indexes
        control_report = redownload_paths(
            resolver,
            control_indexes,
            budget_bytes=budgets["max_control_index_bytes"],
            budget_shards=budgets["max_shards"],
            label="control_indexes",
        )
        # 2) Redownload selected shards
        shard_report = redownload_paths(
            resolver,
            selected_shards,
            budget_bytes=budgets["max_selected_shard_bytes"],
            budget_shards=budgets["max_shards"],
            label="selected_shards",
        )
        total_redownload_bytes = (
            int(control_report["total_bytes"]) + int(shard_report["total_bytes"])
        )
        if total_redownload_bytes > budgets["max_bytes"]:
            raise CanaryBudgetError(
                f"combined redownload {total_redownload_bytes} exceeds "
                f"max_bytes={budgets['max_bytes']}"
            )
        total_files = int(control_report["file_count"]) + int(shard_report["file_count"])
        if total_files > budgets["max_shards"]:
            raise CanaryBudgetError(
                f"combined redownload file_count {total_files} exceeds "
                f"max_shards={budgets['max_shards']}"
            )

        # 3) Sparse queries twice for cache/offline parity
        client = _open_query_client(
            resolver,
            max_bytes=budgets["max_query_bytes"],
            max_shards=budgets["max_query_shards"],
        )
        query_receipts = run_sparse_queries(
            client,
            queries,
            max_bytes=budgets["max_query_bytes"],
            max_shards=budgets["max_query_shards"],
        )

        fetch_trace = resolver.fetch_trace()
        reject_credentials_in_payload(fetch_trace, label="fetch_trace")

        bounded = bool(
            control_report["within_budget"] and shard_report["within_budget"]
        )
        parity = all(bool(item.get("parity_ok")) for item in query_receipts)
        viewer_ok = bool(viewer_report.get("ok"))
        revision_ok = bool(re.fullmatch(r"[0-9a-f]{40}", pin_revision))
        # Policy surface (always true when a canary completes successfully) plus
        # mode-specific gates. Remote runs do not require fixture_canary_offline;
        # fixture runs must never invoke the network.
        acceptance = {
            "bounded_downloads": bounded,
            "cache_offline_parity": parity,
            "fixture_canary_offline": (
                mode_text == "fixture" and not network_invoked
            )
            if mode_text == "fixture"
            else True,  # policy holds; remote path is a separate opt-in gate
            "immutable_revision_required": True,
            "never_infer_mutable_revision": True,
            "network_invoked_only_when_remote": (
                not network_invoked if mode_text == "fixture" else True
            ),
            "read_only": True,
            "remote_opt_in_only": True,
            "remote_staging_coordinates_explicit": (
                mode_text != "remote" or bool(pin_repo and pin_revision)
            ),
            "revision_is_40_hex": revision_ok,
            "viewer_configs_valid": viewer_ok,
        }
        ok = all(bool(v) for v in acceptance.values()) and viewer_ok and bounded and parity

        receipt: dict[str, Any] = {
            "acceptance": acceptance,
            "budgets": budgets,
            "code_version": CODE_VERSION,
            "control_redownload": control_report,
            "default_config": DEFAULT_CONFIG_NAME,
            "disk_viewer": disk_viewer,
            "fetch_trace": {
                "cache_hits": fetch_trace.get("cache_hits"),
                "file_count": fetch_trace.get("file_count"),
                "total_file_bytes": fetch_trace.get("total_file_bytes"),
                "verification_state": fetch_trace.get("verification_state"),
                "revision": fetch_trace.get("revision"),
                "repo_id": fetch_trace.get("repo_id"),
                # Omit per-file absolute paths; keep relative digests only.
                "files": [
                    {
                        "relative_path": f.get("relative_path"),
                        "sha256": f.get("sha256"),
                        "size_bytes": f.get("size_bytes"),
                        "cache_hit": f.get("cache_hit"),
                        "verified": f.get("verified"),
                    }
                    for f in (fetch_trace.get("files") or [])
                    if isinstance(f, Mapping)
                ],
            },
            "goal_id": GOAL_ID,
            "mode": mode_text,
            "network_invoked": network_invoked,
            "ok": ok,
            "producer": PRODUCER,
            "program_id": PROGRAM_ID,
            "queries": query_receipts,
            "read_only": True,
            "release_profile": policy.get("release_profile") or DEFAULT_RELEASE_PROFILE,
            "repo_id": pin_repo,
            "revision": pin_revision,
            "schema": RECEIPT_SCHEMA,
            "selected_shard_redownload": shard_report,
            "staging_branch": policy.get("staging_branch") or DEFAULT_STAGING_BRANCH,
            "task_id": TASK_ID,
            "total_redownload_bytes": total_redownload_bytes,
            "viewer": viewer_report,
        }
        receipt["receipt_sha256"] = digest_mapping(
            {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        )
        reject_credentials_in_payload(receipt, label="canary_receipt")
        return receipt
    finally:
        if staging_tmpdir is not None:
            staging_tmpdir.cleanup()
        if cache_tmpdir is not None:
            cache_tmpdir.cleanup()


def run_fixture_canary(
    *,
    recipe: Mapping[str, Any] | None = None,
    release_root: Path | str | None = None,
    cache_dir: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Offline fixture canary (default validation path)."""

    return run_canary(
        recipe=recipe,
        mode="fixture",
        release_root=release_root,
        cache_dir=cache_dir,
        network=False,
        repo_root=repo_root,
    )


def run_remote_canary(
    *,
    repo_id: str,
    revision: str,
    recipe: Mapping[str, Any] | None = None,
    cache_dir: Path | str | None = None,
    transport: Any | None = None,
    network: bool = False,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Opt-in remote canary at an explicit immutable staging revision."""

    return run_canary(
        recipe=recipe,
        mode="remote",
        repo_id=repo_id,
        revision=revision,
        cache_dir=cache_dir,
        transport=transport,
        network=network,
        repo_root=repo_root,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canary_uscode_hf_release.py",
        description=(
            "Pinned staged-remote canary and Dataset Viewer checks for US Code "
            f"sparse GraphRAG ({TASK_ID}). Default mode is offline fixture "
            "(no Hub contact)."
        ),
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Offline fixture canary mode (no network, deterministic)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check sealed uscode_remote_canary.json against a fresh fixture recipe",
    )
    parser.add_argument(
        "--write-fixture",
        action="store_true",
        help="Rewrite the sealed remote-canary fixture from build_fixture_canary_recipe()",
    )
    parser.add_argument(
        "--repo-id",
        default=None,
        help=(
            "Explicit Hub dataset id for remote canary "
            f"(or ${REMOTE_REPO_ENV})"
        ),
    )
    parser.add_argument(
        "--revision",
        default=None,
        help=(
            "Immutable 40-hex staging revision for remote canary "
            f"(or ${REMOTE_REVISION_ENV}); never main/latest"
        ),
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help=(
            "Opt-in live Hub transport for remote canary "
            "(requires explicit --repo-id and --revision)"
        ),
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=None,
        help="Optional pre-materialized local release root (fixture mode)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Optional resolver cache directory",
    )
    parser.add_argument(
        "--canary-fixture",
        type=Path,
        default=None,
        help="Override path to the sealed remote-canary fixture",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the canary receipt JSON (default: stdout)",
    )
    return parser


def _resolve_remote_coordinates(
    args: argparse.Namespace,
) -> tuple[str | None, str | None]:
    repo = args.repo_id or os.environ.get(REMOTE_REPO_ENV) or None
    rev = args.revision or os.environ.get(REMOTE_REVISION_ENV) or None
    return repo, rev


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except CanaryUscodeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if args.write_fixture:
            if not args.fixture_only:
                raise CanaryUscodeError("--write-fixture requires --fixture-only")
            recipe = build_fixture_canary_recipe()
            out = args.canary_fixture or default_canary_fixture_path()
            write_json(out, recipe)
            print(
                json.dumps(
                    {
                        "status": "fixture_written",
                        "path": str(DEFAULT_CANARY_FIXTURE_RELPATH).replace("\\", "/"),
                        "fixture_id": recipe["fixture_id"],
                        "staging_revision": recipe["staging_revision"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.check:
            result = check_canary_fixture(path=args.canary_fixture)
            write_json(args.output, result)
            return 0

        recipe_path = args.canary_fixture or default_canary_fixture_path()
        recipe = load_json_mapping(recipe_path)

        remote_repo, remote_rev = _resolve_remote_coordinates(args)
        remote_env_enabled = str(os.environ.get(REMOTE_ENABLE_ENV) or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        want_remote = bool(
            args.network
            or remote_env_enabled
            or (remote_repo and remote_rev and not args.fixture_only)
        )

        if args.fixture_only or not want_remote:
            receipt = run_fixture_canary(
                recipe=recipe,
                release_root=args.release_root,
                cache_dir=args.cache_dir,
            )
        else:
            if not remote_repo or not remote_rev:
                raise CanaryRemoteError(
                    "remote canary requires explicit staging coordinates "
                    f"(--repo-id/--revision or ${REMOTE_REPO_ENV}/"
                    f"${REMOTE_REVISION_ENV}); refusing to infer a mutable revision"
                )
            receipt = run_remote_canary(
                repo_id=remote_repo,
                revision=remote_rev,
                recipe=recipe,
                cache_dir=args.cache_dir,
                network=bool(args.network or remote_env_enabled),
            )

        write_json(args.output, receipt)
        return 0 if receipt.get("ok") else 1

    except (
        CanaryUscodeError,
        CanaryBudgetError,
        CanaryViewerError,
        CanaryParityError,
        CanaryRemoteError,
        MutableRevisionError,
        ResolverError,
        UscodeHFReleaseError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
