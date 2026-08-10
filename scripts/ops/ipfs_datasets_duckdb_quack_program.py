#!/usr/bin/env python3
"""Bootstrap, export, launch, and inspect the DuckDB/Quack/DuckLake migration program.

The checked-in Python data below is a reproducible seed migration.  After
``bootstrap`` succeeds, the DuckDB task source is the mutable authority;
Markdown and JSON are deterministic, one-way exports only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import venv
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_MANUAL_GATE_AUTHORITY_PATH = Path(__file__).resolve().with_name(
    "ipfs_datasets_duckdb_quack_manual_gate.py"
)
if (
    _MANUAL_GATE_AUTHORITY_PATH.parent != Path(__file__).resolve().parent
    or not _MANUAL_GATE_AUTHORITY_PATH.is_file()
    or _MANUAL_GATE_AUTHORITY_PATH.is_symlink()
):
    raise RuntimeError("manual-gate authority module is not an exact sibling file")
_MANUAL_GATE_AUTHORITY_SPEC = importlib.util.spec_from_file_location(
    "_ipfs_datasets_duckdb_quack_manual_gate_authority",
    _MANUAL_GATE_AUTHORITY_PATH,
)
if _MANUAL_GATE_AUTHORITY_SPEC is None or _MANUAL_GATE_AUTHORITY_SPEC.loader is None:
    raise RuntimeError("manual-gate authority module cannot be loaded exactly")
manual_gate_authority = importlib.util.module_from_spec(_MANUAL_GATE_AUTHORITY_SPEC)
_MANUAL_GATE_AUTHORITY_SPEC.loader.exec_module(manual_gate_authority)


REPO_ROOT = Path(__file__).resolve().parents[2]
ACCELERATE_ROOT = REPO_ROOT / "ipfs_accelerate_py"
RUNTIME_ROOT = REPO_ROOT / "data/agent_supervisor/ipfs_datasets_duckdb_quack"
DATABASE_PATH = RUNTIME_ROOT / "control.duckdb"
STATE_ROOT = RUNTIME_ROOT / "state"
WORKTREE_ROOT = RUNTIME_ROOT / "worktrees"
MERGE_QUEUE_ROOT = RUNTIME_ROOT / "merge-queue"
MASTER_ROOT = RUNTIME_ROOT / "master"
MASTER_LOG = MASTER_ROOT / "supervisor.log"
MASTER_PID = MASTER_ROOT / "supervisor.pid"
MASTER_IDENTITY = MASTER_ROOT / "supervisor.identity.json"
MANUAL_GATE_LIFECYCLE_ROOT = RUNTIME_ROOT / "manual-gates"
MANUAL_GATE_LIFECYCLE_LOCK = MANUAL_GATE_LIFECYCLE_ROOT / ".lifecycle.lock"
MANUAL_GATE_AUTHORITY_MODULE = (
    _MANUAL_GATE_AUTHORITY_PATH
)
MANUAL_GATE_JOURNAL_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-journal@2"
)
MANUAL_GATE_EXECUTION_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-verifier-execution@2"
)
MANUAL_GATE_CAS_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-cas-receipt@2"
)
MANUAL_GATE_RELEASE_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-release@2"
)
MANUAL_GATE_DRAIN_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-manual-gate-runtime-drain@2"
)
MANUAL_GATE_PHASES = (
    "PREPARED",
    "DRAIN_PREPARED",
    "DRAINED",
    "EXECUTION_PREPARED",
    "EFFECT_PREPARED",
    "EFFECT_APPLIED",
    "CAS_COMMITTED",
    "RELAUNCHED",
    "RELEASE_PREPARED",
    "RELEASED",
)
_MANUAL_GATE_CUSTODIAN_PROCESSES: dict[int, subprocess.Popen[bytes]] = {}
RETRY_LIFECYCLE_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-lifecycle-journal@1"
)
RETRY_LIFECYCLE_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-lifecycle-receipt@1"
)
RETRY_RESET_ANCHOR_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-reset-anchor@1"
)
RETRY_CHECKOUT_LEASE_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-checkout-lease@1"
)
RETRY_CHECKOUT_LEASE_OWNER_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-checkout-lease-owner@1"
)
RETRY_CHECKOUT_RELEASE_TOMBSTONE_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-checkout-release-tombstone@1"
)
RETRY_CHECKOUT_RELEASE_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-checkout-release-receipt@1"
)
RETRY_CHECKOUT_FINALIZATION_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-checkout-finalization@1"
)
RETRY_CHECKOUT_EXECUTION_ASSERTION_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-retry-checkout-execution-assertion@1"
)
RETRY_LIFECYCLE_PHASES = frozenset(
    {
        "prepared",
        "draining",
        "drained",
        "leased",
        "reset_committed",
        "relaunching",
        "finalizing",
        "completed",
    }
)
EXPECTED_ENV_ROOT = Path(
    os.environ.get(
        "IPFS_DATASETS_DQK_ENV_ROOT",
        str(REPO_ROOT.parents[1] / ".venvs/ipfs-datasets-duckdb-quack"),
    )
).resolve()
ENVIRONMENT_RECEIPT = EXPECTED_ENV_ROOT / "environment-receipt.json"
SEALED_PYTHON_LAUNCHER = EXPECTED_ENV_ROOT / "bin/dqk-sealed-python"
ENVIRONMENT_LIFECYCLE_LOCK = (
    EXPECTED_ENV_ROOT.parent / ".ipfs-datasets-duckdb-quack-environment.lock"
)
BOOTSTRAP_REQUIREMENTS = REPO_ROOT / "requirements/duckdb-quack-bootstrap.lock"
BOOTSTRAP_REQUIREMENTS_SHA256 = (
    "sha256:a8759c24689337513d574a5517fd4616f07e0994e75afa38478855642e4f0ef1"
)
BOOTSTRAP_VALIDATOR = (
    REPO_ROOT / "scripts/ops/ipfs_datasets_duckdb_quack_validator.py"
)
BOOTSTRAP_VALIDATOR_REQUIREMENTS = (
    REPO_ROOT / "requirements/duckdb-quack-validator.lock"
)
BOOTSTRAP_VALIDATOR_REQUIREMENTS_SHA256 = (
    "sha256:839b484c8f448dc722cc1443a5961d3a5afd1bb6eae1d9b2d4e0091fdebab655"
)
BOOTSTRAP_VALIDATOR_SHA256 = (
    "sha256:d4e842721ff15ab428cd2481429481bcca6ce17899a1b1c8441e317c99816c49"
)
BOOTSTRAP_VALIDATOR_ROOT = Path(
    os.environ.get(
        "IPFS_DATASETS_DQK_VALIDATOR_ROOT",
        str(EXPECTED_ENV_ROOT.parent / "ipfs-datasets-duckdb-quack-validator"),
    )
).resolve()
TASK_VALIDATION_PYTHON = BOOTSTRAP_VALIDATOR_ROOT / "bin/python"
TASK_VALIDATION_PYTHON_SHA256 = (
    "sha256:8b610568a8b2f6fe83d03746b0aac7db229546de5bbbe7bb60469caed72bc55a"
)
TASK_VALIDATION_DISPATCH_SHA256 = (
    "sha256:758ee449765b2bb120d0fe2ce27091df863516cc50c0339f7b8160ba178e3ffb"
)
TASK_VALIDATOR_RECEIPT_ID = (
    "sha256:b0cb231350216a166e798f61c808b27ebb6116faba420f91c7a2a02248b9ed9a"
)
TASK_VALIDATOR_CACHE_RECEIPT_ID = (
    "sha256:1b6b1e8a6ecf352d6602cf52c86d04e4d83f1809b6013e83ac44f841ccd0df6c"
)
BOOTSTRAP_BRIDGE_VALIDATION_TESTS = (
    "test/api/test_agent_supervisor_implementation_daemon_runner.py",
    "test/api/test_agent_supervisor_task_source_e2e.py",
    "test/api/test_agent_supervisor_duckdb_task_source.py",
    "test/api/test_agent_supervisor_duckdb_completion_evidence.py",
    "test/api/test_agent_supervisor_duckdb_retry_reset.py",
    "test/api/test_agent_supervisor_duckdb_merge_evidence_e2e.py",
)
BOOTSTRAP_ENVIRONMENT_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/duckdb-quack-bootstrap-environment-receipt@1"
)
BOOTSTRAP_SUPPORTED_PYTHON = (3, 12)
BOOTSTRAP_SUPPORTED_SYSTEM = "Linux"
BOOTSTRAP_SUPPORTED_MACHINES = frozenset({"aarch64", "x86_64"})
DEFAULT_MARKDOWN_EXPORT = (
    REPO_ROOT
    / "docs/architecture/IPFS_DATASETS_DUCKDB_QUACK_CONTROL_PLANE_PLAN.md"
)
DEFAULT_JSON_EXPORT = RUNTIME_ROOT / "exports/ipfs_datasets_duckdb_quack_plan.json"
PROGRAM_SCHEMA = "ipfs_datasets_py/duckdb-quack-migration-program@1"
PROGRAM_ID = "ipfs-datasets-duckdb-quack-v1"
# Concurrent implementation lanes (each lane = one implementer + shard).
# Raised from 2 once host capacity and merge serialization were proven.
MAX_IMPLEMENTATION_LANES = 4
BOARD_NAMESPACE = "ipfs-datasets-duckdb-quack"
TARGET_BRANCH = "feat/duckdb-quack-control-plane"
ROOT_GOAL_ID = "DQK-G000"
ROOT_GOAL_CID = "goal:cid:dqk-g000"
BOOTSTRAP_TASK_ID = "DQK-007"
RELEASE_VERIFIER_TASK_ID = "DQK-057"
RELEASE_GATE_TASK_ID = "DQK-056"
REFINEMENT_GATE_TASK_ID = "DQK-081"
PROMOTION_GATE_TASK_ID = "DQK-102"
RUNTIME_ACTIVATION_GATE_TASK_ID = "DQK-103"
MANUAL_GATE_TASK_IDS = frozenset(
    {
        RELEASE_GATE_TASK_ID,
        REFINEMENT_GATE_TASK_ID,
        PROMOTION_GATE_TASK_ID,
        RUNTIME_ACTIVATION_GATE_TASK_ID,
    }
)
MANUAL_GATE_OWNER_TASK_IDS = {
    RELEASE_GATE_TASK_ID: RELEASE_VERIFIER_TASK_ID,
    REFINEMENT_GATE_TASK_ID: "DQK-080",
    PROMOTION_GATE_TASK_ID: "DQK-100",
    RUNTIME_ACTIVATION_GATE_TASK_ID: "DQK-083",
}
MANUAL_GATE_AUTHORITY_EFFECT_IDS = {
    task_id: f"authority:manual-gate:{task_id.lower()}"
    for task_id in MANUAL_GATE_TASK_IDS
}
REQUIRED_ACCELERATE_BRIDGE_COMMIT = "83cb0cdabb581a547ffb9f74119cef0bb431fc24"
REQUIRED_DUCKDB_VERSION = (1, 5, 5)
MINIMUM_QUACK_VERSION = (1, 5, 3)
EXPORT_TABLES = (
    "goals",
    "tasks",
    "task_dependencies",
    "task_outputs",
    "task_validations",
    "task_acceptance",
    "task_events",
    "materialization_receipts",
)
EXPECTED_IDLE_SELECTION_REASONS = frozenset(
    {
        "no_ready_tasks",
        "no_selectable_ready_tasks",
        "no_shard_selectable_ready_tasks",
    }
)
_ACCELERATE_IMPORT_ENVIRONMENT = {
    "IPFS_ACCEL_SKIP_CORE": "1",
    "IPFS_ACCEL_IMPORT_EAGER": "0",
    "IPFS_ACCELERATE_PY_DISABLE_SECRET_MANAGER": "1",
}


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _accelerate_module_has_protected_origin(module: Any) -> bool:
    """Return whether every available module/package origin is protected."""

    origins: list[Path] = []
    module_file = getattr(module, "__file__", None)
    if module_file:
        origins.append(Path(str(module_file)))
    module_path = getattr(module, "__path__", None)
    if module_path is not None:
        origins.extend(Path(str(item)) for item in module_path)
    return bool(origins) and all(
        _path_is_within(origin, ACCELERATE_ROOT) for origin in origins
    )


def _reject_preloaded_foreign_accelerate_modules() -> None:
    for name, module in tuple(sys.modules.items()):
        if not (
            name == "ipfs_accelerate_py"
            or name.startswith("ipfs_accelerate_py.")
        ):
            continue
        if module is None or not _accelerate_module_has_protected_origin(module):
            raise RuntimeError(
                f"preloaded accelerator module has a foreign origin: {name}"
            )


def _accelerate_module(canonical_name: str, legacy_name: str) -> Any:
    """Import the released supervisor layout with a bridge-era fallback.

    The running DQP release moved task sources, planning, and proof contracts
    into their canonical subpackages.  The bootstrap bridge predates that
    layout.  Only a genuinely missing canonical module permits the legacy
    fallback; an import failure inside an existing canonical module remains a
    hard error instead of silently selecting different authority code.
    """

    os.environ.update(_ACCELERATE_IMPORT_ENVIRONMENT)
    _reject_preloaded_foreign_accelerate_modules()
    selected_root = ACCELERATE_ROOT.resolve()
    sys.path[:] = [
        item
        for item in sys.path
        if not _path_is_within(Path(str(item or os.curdir)), selected_root)
        or Path(str(item or os.curdir)).resolve() != selected_root
    ]
    sys.path.insert(0, str(selected_root))
    try:
        selected_module = importlib.import_module(canonical_name)
    except ModuleNotFoundError as exc:
        missing = str(exc.name or "")
        if not missing or not (
            missing == canonical_name
            or canonical_name.startswith(f"{missing}.")
        ):
            raise
        selected_module = importlib.import_module(legacy_name)
    if not _accelerate_module_has_protected_origin(selected_module):
        raise RuntimeError(
            "imported accelerator module has a foreign origin: "
            f"{getattr(selected_module, '__name__', canonical_name)}"
        )
    return selected_module


ARCHITECTURE: dict[str, Any] = {
    "decision": (
        "DuckDB tables become the authority for mutable orchestration, planning, "
        "analysis, lifecycle events, and normalized query projections. DuckLake is "
        "the governed lakehouse layer for snapshot-consistent aggregation of many "
        "Parquet datasets. Quack is a replaceable DuckDB-to-DuckDB SQL transport; "
        "neither DuckLake nor Quack is the scheduler."
    ),
    "principles": [
        "No mutable operational truth in Markdown, JSON, JSONL, YAML, or ad-hoc text files.",
        "Keep versioned executable migrations and seed migrations in Git with checksums.",
        "Make Markdown/JSON deterministic one-way exports bound to a schema, revision, query, and digest.",
        "Keep large immutable bytes in IPLD/CAR/Parquet/object storage and address them by CID from DuckDB.",
        "Use DuckLake for Parquet lakehouse metadata, snapshot history, and analytical aggregation; never use it as task, lease, proof, wallet, or idempotency authority.",
        "Base the distributed DuckLake catalog plane on DuckDB + Quack: exactly one fenced DuckDB/Quack owner process opens each DuckDB-backed catalog file, while every distributed caller uses the authenticated remote protocol rather than opening that file directly.",
        "Quack lets many remote client processes use one DuckDB-backed catalog through its sole owner, but those clients never open the file and Quack supplies no replication, consensus, or high availability.",
        "Scale through independently fenced catalog shards and snapshot-vector federation rather than multiple owners of one catalog file.",
        "Manage DuckLake remotely through a dedicated trusted DuckDB + Quack catalog gateway whose token and storage credentials remain inside an allowlisted owner broker; agents submit typed operations rather than raw SQL.",
        "Separate the small control writer from graph/vector/proof/wallet analytical catalogs.",
        "Use short transactions, compare-and-swap revisions, fenced leases, idempotency keys, and append-only events.",
        "Treat every Quack endpoint as a full-SQL trust boundary and expose allowlisted views or query templates.",
        "Publish sanitized, physically separate read models to remote Quack clients; never attach authority catalogs to an untrusted session.",
        "Preserve existing proof authority, graph revision, vector generation, AST provenance, and wallet reorg semantics.",
        "Use shadow reads/writes and parity receipts before changing authority for any domain.",
        "Never put wallet secrets, signing material, unrestricted raw payloads, or private keys on the Quack surface.",
    ],
    "topology": {
        "control": (
            "Small authoritative DuckDB database for programs, goals, tasks, dependencies, "
            "attempts, leases, heartbeats, blockers, events, validation and merge receipts."
        ),
        "graph_vector": (
            "Graph metadata, normalized projections, vector lifecycle metadata, and read-only "
            "views over immutable Parquet/IPLD revisions."
        ),
        "proof": (
            "Proof keys, authority dimensions, attempts, evidence, attestations, invalidations, "
            "revocations, and CID references to canonical proof envelopes."
        ),
        "ast": (
            "Source revisions, files, spans, scopes, symbols, imports, references, calls, effects, "
            "diagnostics, invalidations, and code-evidence graph projections."
        ),
        "wallet": (
            "Public normalized ledger facts, checkpoints, finality and reorg state; encrypted/raw "
            "objects remain outside the general SQL surface."
        ),
        "ducklake": (
            "Each DuckLake v1.0 catalog shard uses a DuckDB metadata file on local or attached "
            "block storage, opened by exactly one "
            "fenced DuckDB + Quack owner process over owned lifecycle-managed Parquet namespaces "
            "in local or versioned object storage. Distributed workers reach the owner through "
            "Quack and federate explicit per-shard snapshot versions; they never open a shard's "
            "catalog file directly. Source IPLD/IPFS CIDs remain immutable provenance rather than "
            "DuckLake DATA_PATHs, while control, proof, wallet, and agent state remain authoritative "
            "in their transaction-specific stores."
        ),
        "quack_gateway": (
            "Pinned DuckDB/Quack server processes use separate endpoint, credential, OS, and network "
            "identities for the internal DuckLake catalog manager and sanitized publication gateways. "
            "The trusted owner broker retains the catalog-manager token and emits only typed operations; "
            "untrusted clients can reach only the physically separate publication database. A TLS reverse "
            "proxy is required for any remote access."
        ),
    },
    "catalogs": {
        "meta": [
            "schema_registry",
            "schema_migrations",
            "migration_batches",
            "extension_locks",
            "capability_probes",
            "source_artifacts",
            "export_jobs",
            "snapshot_receipts",
        ],
        "control": [
            "programs",
            "goals",
            "goal_edges",
            "tasks",
            "task_dependencies",
            "task_attempts",
            "task_claims",
            "leases",
            "heartbeats",
            "idempotency_keys",
            "blockers",
            "validations",
            "acceptance_evidence",
            "merge_receipts",
            "events",
        ],
        "graphs": [
            "graphs",
            "branches",
            "revisions",
            "vertices",
            "edges",
            "properties",
            "adjacency",
            "pins",
            "tombstones",
            "parquet_segments",
            "lineage",
        ],
        "vectors": [
            "vector_collections",
            "embedding_models",
            "vector_documents",
            "vector_chunks",
            "vector_values_by_dimension",
            "vector_shards",
            "vector_index_builds",
            "vector_tombstones",
            "vector_compactions",
        ],
        "proofs": [
            "proof_keys",
            "proof_entries",
            "proof_key_dimensions",
            "premises",
            "solver_runs",
            "proof_evidence",
            "attestations",
            "invalidations",
            "revocations",
            "singleflight_claims",
            "access_statistics",
        ],
        "asts": [
            "source_revisions",
            "source_files",
            "ast_blobs",
            "ast_nodes",
            "scopes",
            "symbols",
            "imports",
            "references",
            "calls",
            "effects",
            "interfaces",
            "diagnostics",
            "invalidations",
        ],
        "wallet": [
            "chains",
            "ingestion_sources",
            "accounts",
            "assets",
            "blocks",
            "transactions",
            "transfers",
            "utxos",
            "token_accounts",
            "contract_events",
            "cursors",
            "checkpoints",
            "finality_transitions",
            "reorgs",
            "encrypted_object_refs",
        ],
        "observability": [
            "lifecycle_events",
            "traces",
            "spans",
            "health_samples",
            "query_profiles",
            "dead_letters",
            "audit_events",
        ],
        "ducklake_registry": [
            "lake_catalogs",
            "lake_catalog_shards",
            "lake_dataset_home_shards",
            "lake_catalog_owner_generations",
            "lake_datasets",
            "lake_sources",
            "lake_schema_contracts",
            "lake_snapshot_vectors",
            "lake_snapshot_vector_roots",
            "lake_shard_migrations",
            "lake_ingest_receipts",
            "lake_file_identities",
            "lake_maintenance_jobs",
            "lake_backup_receipts",
            "lake_publication_receipts",
            "lake_release_receipts",
        ],
    },
    "rollout": [
        "Inventory and classify authored documents, mutable state, immutable evidence, and derived exports.",
        "Install schema registry, checksummed migrations, capability gates, and connection policy.",
        "Import legacy state in bounded idempotent batches while retaining original byte digests and reject rows.",
        "Run DuckDB as a shadow projection and emit differential/parity receipts.",
        "Admit owned Parquet copies into DuckLake under content-bound source, schema, ownership-transfer, and snapshot receipts.",
        "Enable dual writes with a crash-recoverable outbox or journal and quarantine disagreements.",
        "Canary one namespace per domain; prove restore, rollback, and fail-closed behavior.",
        "Promote DuckDB authority only after acceptance gates and make legacy files export-only.",
        "Scan the repository and runtime roots for residual file-authoritative producers before final cutover.",
    ],
    "quack_constraints": [
        "Pin DuckDB and Quack to 1.5.5 initially and repeat compatibility tests before every update.",
        "Quack is experimental/beta and not production-ready until DuckDB 2.0; keep a local transport implementation and feature gate, and require an explicit compatibility/risk receipt before any production promotion.",
        "Prefer stateless single-statement server-side SQL for mutations; avoid remote ALTER and direct attached UPDATE/DELETE dependencies.",
        "Retry optimistic transaction conflicts with bounded jitter and make every mutation idempotent.",
        "Quack has no server push, task queue, lease manager, replication, failover, or watchdog; the supervisor supplies task/lease/watchdog/fencing/restart orchestration, DQK-098 supplies cold recovery, and no component claims active replication or high availability.",
        "Use loopback, per-operation credentials, restricted OS identities, and a TLS reverse proxy for remote use. Publication gateways disable external access; catalog owners deny by default but allow only pinned local paths/extensions and exact object-storage/TLS-proxy egress required by their shard.",
        "DuckDB has no GRANT-style catalog ACL boundary: never serve or ATTACH control, proof, or wallet authority catalogs to an untrusted Quack session.",
        "A dedicated internal Quack endpoint may drive DuckDB DuckLake catalog operations only when its reusable token remains inside the trusted broker, one-use worker authentication is enforced by a non-default fresh-connection authentication callback or authenticating proxy, object credentials are short-lived, and every statement comes from an independently verified allowlisted typed operation.",
    ],
    "ducklake_constraints": [
        "Pin every explicitly loaded DuckLake catalog-owner artifact (ducklake, quack, and required httpfs/cloud adapters) to the admitted DuckDB platform; explicitly load them before locking configuration and disabling automatic installation, loading, and catalog migration.",
        "A DuckDB-backed DuckLake catalog is single-client: exactly one fenced DuckDB + Quack owner process may open each catalog file, and all distributed readers/writers must use that owner's remote typed interface.",
        "Keep live read/write catalog and companion-registry files on local or attached block storage; reject NFS, SMB, object URLs, and shared filesystem mounts for authority files, while Parquet data may use governed object storage.",
        "A successor owner may open a catalog only after the predecessor stopped admission, its endpoint/token was revoked, storage capabilities expired, every file handle closed, and the successor acquired both the durable generation lease and DuckDB's native file lock.",
        "Partition scale across independent DuckDB catalog shards and federate them with an explicit snapshot vector; never load-balance mutating requests across two active owners of the same catalog file.",
        "Treat every DuckLake mutation as a new catalog-global snapshot and bind multi-catalog queries to one explicit snapshot-version member per catalog because independent catalogs do not share one atomic transaction.",
        "DuckLake does not enforce indexes, primary keys, unique keys, foreign keys, or CHECK constraints; validate domain contracts before commit and persist reject evidence.",
        "Register only files in an owned lake namespace: adding an existing Parquet file transfers lifecycle ownership and later compaction or cleanup may delete it.",
        "Keep automatic migration off; an owner-gated migration must verify catalog version, backup both catalog metadata and Parquet storage, and emit a rollback receipt.",
        "Expire snapshots only under a catalog-global retention class before cleaning files, honor authoritative reader leases, dry-run destructive maintenance, and separately reconcile scheduled and orphan files.",
        "Enforce access through the owner broker, Quack authorization callback, catalog-owner OS identity, and object-store IAM; DuckLake itself is not the security boundary and its encrypted-file keys make the catalog sensitive.",
        "Never expose the authority DuckLake catalog, raw SQL surface, Quack token, or catalog credentials to agents: the dedicated trusted DuckDB + Quack catalog manager is broker-only, while agent queries use typed APIs or fenced sanitized snapshot copies in the physically separate publication database.",
    ],
    "success_metrics": [
        "Zero mutable orchestration/planning/analysis/logging authorities remain in Markdown or JSON after cutover.",
        "Every schema and extension change is checksummed, replayable, and covered by compatibility tests.",
        "No duplicate task execution or stale publication after lease expiry, crash, or lost response.",
        "Graph, vector, proof, AST, and wallet predicates can execute in parallel without starving control-plane heartbeats.",
        "Multiple admitted Parquet datasets can be queried through a reproducible DuckLake snapshot vector while concurrent writers, retries, compaction, and cold failover converge to one logical outcome per operation ID.",
        "Every remote DuckLake catalog mutation is executed by DuckDB over the internal Quack manager from a signed typed operation; a crash may leave a bounded in-doubt snapshot, but restart reconciliation must map its persisted operation ID to one terminal receipt or quarantine without a second logical transition.",
        "Every export is reproducible from an identified database snapshot and verifies its digest.",
        "The 970 MB production-hardening fixture migrates by streaming within declared memory and time budgets.",
        "Backup/restore, parity, tamper, secret-scanning, concurrency, and chaos gates are green before authority promotion.",
    ],
    "risks": {
        "quack_beta": "Keep transport replaceable, pin 1.5.5, contract-test known gaps, and requalify at DuckDB 2.0.",
        "writer_contention": "Use one short-transaction writer per database, leases/fencing, outboxes, and workload-separated catalogs.",
        "cid_drift": "Preserve canonical source bytes and normalization rules; never reconstruct identity-bearing proof or graph bytes from lossy columns.",
        "vector_index": "Treat DuckDB VSS/HNSW as rebuildable derived state; exact FLOAT[N] vectors and content digests remain authoritative.",
        "sql_surface": "Deny arbitrary remote SQL for untrusted agents and forbid read_* functions, extension changes, secrets, filesystem, and network access.",
        "wallet_exposure": "Project public ledger facts only; keep secrets and unrestricted raw payloads encrypted and out of Quack-visible catalogs.",
        "large_migration": "Stream and checkpoint batches; retain source hashes, rejects, resumable cursors, and bounded memory.",
        "cross_database_atomicity": "Use transactional outboxes, immutable receipts, CIDs, and idempotent reconciliation rather than assuming cross-file atomicity.",
        "ducklake_catalog": "Use one fenced DuckDB + Quack owner per catalog shard, serialize same-shard mutations through typed idempotent operations, federate shards by snapshot vector, and never mistake lake snapshots or Quack transport for control-plane CAS authority.",
        "ducklake_file_lifecycle": "Copy sources into a lifecycle-managed owned namespace before registration; retain source CIDs as provenance and gate snapshot expiry, compaction, and orphan cleanup with dry-run evidence, authoritative reader leases, catalog-global retention, and restore tests.",
    },
}


GOALS: tuple[dict[str, Any], ...] = (
    {
        "goal_id": ROOT_GOAL_ID,
        "goal_cid": ROOT_GOAL_CID,
        "title": "Make DuckDB the typed authority and Quack the guarded SQL access plane",
        "objective": ARCHITECTURE["decision"],
        "acceptance_criteria": ARCHITECTURE["success_metrics"],
        "architecture": ARCHITECTURE,
    },
    {
        "goal_id": "DQK-G100",
        "goal_cid": "goal:cid:dqk-g100",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Authority, schema, identity, and connection kernel",
        "acceptance_criteria": ["Migrations replay deterministically", "Capabilities and extension versions fail closed"],
    },
    {
        "goal_id": "DQK-G200",
        "goal_cid": "goal:cid:dqk-g200",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "DuckDB-native agent supervisor control plane",
        "acceptance_criteria": ["Goals/tasks/events are database authoritative", "Expired or stalled work is recovered without duplicate publication", "Plan and runtime generations activate only through an external journaled lifecycle owner"],
    },
    {
        "goal_id": "DQK-G300",
        "goal_cid": "goal:cid:dqk-g300",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Knowledge graph catalog, revisions, and query plane",
        "acceptance_criteria": ["SQLite/JSON catalog semantics survive migration", "Parquet/IPLD identities and branch CAS remain intact"],
    },
    {
        "goal_id": "DQK-G400",
        "goal_cid": "goal:cid:dqk-g400",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Typed vector lifecycle and hybrid retrieval",
        "acceptance_criteria": ["No pickle metadata authority", "Exact and derived indexes have differential parity"],
    },
    {
        "goal_id": "DQK-G500",
        "goal_cid": "goal:cid:dqk-g500",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Unified proof cache, evidence, and corpus projection",
        "acceptance_criteria": ["All authority dimensions are retained", "Revoked or stale proofs fail closed"],
    },
    {
        "goal_id": "DQK-G600",
        "goal_cid": "goal:cid:dqk-g600",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "AST and code-evidence relational projection",
        "acceptance_criteria": ["Incremental source revisions preserve spans and CIDs", "Impact queries join AST, proof, and graph state"],
    },
    {
        "goal_id": "DQK-G700",
        "goal_cid": "goal:cid:dqk-g700",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Privacy-safe multi-chain wallet transaction plane",
        "acceptance_criteria": ["Reorg/finality/checkpoint semantics pass", "No secret reaches a Quack-visible column"],
    },
    {
        "goal_id": "DQK-G800",
        "goal_cid": "goal:cid:dqk-g800",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Parallel federated query and secure Quack gateway",
        "acceptance_criteria": ["Queries span domains under budgets", "Control heartbeats remain within SLO during analytical load"],
    },
    {
        "goal_id": "DQK-G900",
        "goal_cid": "goal:cid:dqk-g900",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Streaming imports, deterministic exports, and authority rollout",
        "acceptance_criteria": ["Imports are resumable and idempotent", "Exports never become implicit write authorities"],
    },
    {
        "goal_id": "DQK-G1000",
        "goal_cid": "goal:cid:dqk-g1000",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Security, observability, recovery, and compatibility",
        "acceptance_criteria": ["Threat, chaos, restore, and compatibility gates pass", "Every blocker is typed and queryable"],
    },
    {
        "goal_id": "DQK-G1100",
        "goal_cid": "goal:cid:dqk-g1100",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "Canary cutover and database-native self-improvement loop",
        "acceptance_criteria": ["Canary promotion and rollback are proven", "Residual analysis creates bounded database-native subgoals/tasks"],
    },
    {
        "goal_id": "DQK-G1200",
        "goal_cid": "goal:cid:dqk-g1200",
        "parent_goal_cid": ROOT_GOAL_CID,
        "title": "DuckLake distributed Parquet lakehouse and aggregation layer",
        "acceptance_criteria": [
            "Many Parquet datasets are admitted and queried through reproducible snapshot vectors",
            "The distributed catalog plane consists of independently fenced DuckDB + Quack catalog owners; no second client opens an owned catalog file",
            "Remote writers, maintenance, restore, and publication preserve authority and security boundaries",
        ],
    },
    {
        "goal_id": "DQK-G1210",
        "goal_cid": "goal:cid:dqk-g1210",
        "parent_goal_cid": "goal:cid:dqk-g1200",
        "title": "DuckLake catalog, storage, source admission, and ingestion",
        "acceptance_criteria": [
            "The catalog/storage profile is versioned, reproducible, and fail closed",
            "Every admitted Parquet file has schema, content, provenance, ownership, and snapshot evidence",
        ],
    },
    {
        "goal_id": "DQK-G1220",
        "goal_cid": "goal:cid:dqk-g1220",
        "parent_goal_cid": "goal:cid:dqk-g1200",
        "title": "DuckDB + Quack catalog management, snapshot-consistent federation, and parallel query",
        "acceptance_criteria": [
            "A trusted broker manages every DuckDB-backed DuckLake catalog through its single fenced DuckDB + Quack owner without exposing raw SQL or credentials to agents",
            "Cross-dataset queries bind an explicit snapshot vector and schema contract",
            "Same-shard requests are serialized and idempotent while independent catalog shards execute concurrently and remain observable",
        ],
    },
    {
        "goal_id": "DQK-G1230",
        "goal_cid": "goal:cid:dqk-g1230",
        "parent_goal_cid": "goal:cid:dqk-g1200",
        "title": "DuckLake security, lifecycle maintenance, recovery, and cutover",
        "acceptance_criteria": [
            "Catalog and object-store permissions, encryption, backup, retention, and cleanup gates pass",
            "Broker-authenticated typed operations reach the private catalog-owner Quack endpoints, while untrusted agents reach only sanitized snapshot-bound projections through the separate publication gateway and legacy manifest authority is removed",
        ],
    },
)


def _task(
    task_id: str,
    goal_id: str,
    title: str,
    objective: str,
    *,
    depends_on: Sequence[str] = (),
    outputs: Sequence[str],
    validations: Sequence[str],
    acceptance: Sequence[str],
    track: str,
    priority: str = "P1",
    completion: str = "code",
    schedulable: bool = True,
    external_prerequisites: Sequence[str] = (),
    initial_status: str = "pending",
    blocked_reason: str = "",
    authority_effect: str = "",
) -> dict[str, Any]:
    effects = [
        {
            "effect_id": f"effect:{task_id.lower()}:{index}",
            "operation": "assign",
            "fluent_id": f"output:{path}",
            "path": path,
            "value": "modify",
        }
        for index, path in enumerate(outputs)
    ]
    if authority_effect:
        effects.append(
            {
                "effect_id": f"effect:{task_id.lower()}:manual-authority",
                "operation": "assign",
                "fluent_id": authority_effect,
                "value": (
                    "ipfs_datasets_py/manual-gate-authority-effect@1:"
                    f"{task_id}:{MANUAL_GATE_OWNER_TASK_IDS[task_id]}:"
                    "blocked-to-completed:authenticated-execution-required"
                ),
            }
        )
    return {
        "task_id": task_id,
        "goal_id": goal_id,
        "title": title,
        "objective": objective,
        "depends_on": list(depends_on),
        "actor_id": "agent:ipfs-accelerate-supervisor",
        "resource_needs": ["git-worktree", "duckdb"],
        "changed_ast_scopes": [f"path:{path}" for path in outputs],
        "scope_paths": list(outputs),
        "effects": effects,
        "validation_commands": list(validations),
        "acceptance_criteria": list(acceptance),
        "status": initial_status,
        "completion": completion,
        "is_schedulable": bool(schedulable),
        "external_prerequisites": list(external_prerequisites),
        "blocked_reason": str(blocked_reason).strip(),
        "priority": priority,
        "track": track,
        "provenance": {
            "program_id": PROGRAM_ID,
            "program_schema": PROGRAM_SCHEMA,
        },
    }


TASKS: tuple[dict[str, Any], ...] = (
    _task(
        "DQK-001", "DQK-G100", "Inventory and classify every file-authoritative producer",
        "Build a bounded scanner and registry that distinguishes authored documentation, mutable state, immutable evidence, derived exports, and unsafe serialization across datasets and supervisor trees.",
        outputs=("ipfs_datasets_py/duckdb_control/inventory.py", "tests/unit/duckdb_control/test_inventory.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_inventory.py",),
        acceptance=("The scanner is streaming and deterministic", "The 970 MB production-hardening corpus can be inventoried without loading it into memory", "Every record includes path, kind, size, digest, producer, consumer, and proposed authority"),
        track="foundation",
    ),
    _task(
        "DQK-002", "DQK-G100", "Pin DuckDB/Quack and implement capability gates",
        "Create a single dependency/version policy and runtime probe for DuckDB 1.5.5, the exact Quack extension build, VSS availability, protocol compatibility, and safe fallback behavior.",
        outputs=("ipfs_datasets_py/duckdb_control/capabilities.py", "tests/unit/duckdb_control/test_capabilities.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_capabilities.py",),
        acceptance=("Mismatched server/client/extension versions fail closed", "Quack beta status is explicit", "VSS and Quack are optional feature-gated capabilities rather than import-time requirements"),
        track="foundation",
    ),
    _task(
        "DQK-003", "DQK-G100", "Implement schema registry and checksummed migrations",
        "Add namespaced, ordered, replayable migrations with compatibility windows, checksums, lock ownership, dry-run, resume, rollback metadata, and immutable receipts.",
        depends_on=("DQK-001",),
        outputs=("ipfs_datasets_py/duckdb_control/migrations.py", "tests/unit/duckdb_control/test_migrations.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_migrations.py",),
        acceptance=("A fresh database and an upgraded database converge to the same schema digest", "Interrupted migrations resume or fail closed", "Unknown or modified migration checksums are rejected"),
        track="foundation",
    ),
    _task(
        "DQK-004", "DQK-G100", "Define canonical identity, provenance, and blob-reference contracts",
        "Create strict shared contracts for schema IDs, database snapshots, CIDs, source byte digests, normalized timestamps, idempotency keys, export receipts, and immutable IPLD/CAR/Parquet references.",
        depends_on=("DQK-001",),
        outputs=("ipfs_datasets_py/duckdb_control/contracts.py", "tests/unit/duckdb_control/test_contracts.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_contracts.py",),
        acceptance=("Identity-bearing source bytes round-trip without normalization drift", "JSON/floating/timestamp edge cases are covered", "Content references are storage-neutral and tamper evident"),
        track="foundation",
    ),
    _task(
        "DQK-005", "DQK-G100", "Build local and Quack catalog connection policy",
        "Implement short-lived local writer/read connections, attached read-only analytical catalogs, Quack URI/secrets handling, statement budgets, external-access denial, and workload isolation.",
        depends_on=("DQK-002", "DQK-003"),
        outputs=("ipfs_datasets_py/duckdb_control/connections.py", "tests/unit/duckdb_control/test_connections.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_connections.py",),
        acceptance=("Control and analytical workloads use separate connection pools/catalogs", "Writers use bounded short transactions", "Untrusted connections cannot autoload extensions or access filesystem/network surfaces"),
        track="foundation",
    ),
    _task(
        "DQK-082", "DQK-G100", "Provision and attest the pinned DuckDB, Quack, and DuckLake execution environment",
        "Build, without changing the running supervisor generation, a hash-locked isolated Python environment plus explicit Quack and DuckLake extension profiles for DuckDB 1.5.5, verify client/server/extension compatibility and provider tooling, disable automatic installation/loading after provisioning, and emit a content-bound candidate-environment receipt consumed by the DQK-103 lifecycle owner before live transport and lakehouse tasks. Before task dispatch, preflight Docker socket access, pull every digest-pinned service image, run a disposable probe container, and prove sufficient workspace, image, and volume disk capacity.",
        depends_on=("DQK-002", "DQK-005"),
        outputs=("requirements/duckdb-quack.lock", "scripts/ops/create_duckdb_quack_env.py", "tests/compatibility/test_duckdb_quack_environment.py"),
        validations=("python -m pytest -q tests/compatibility/test_duckdb_quack_environment.py",),
        acceptance=("The candidate environment is isolated from unrelated supervisors and reproducible from hashes", "Completing DQK-082 does not change the current master, lane, daemon, or writer generation", "DuckDB is exactly 1.5.5 and the Quack and DuckLake extension/profile checksums are pinned", "Automatic extension install/load and DuckLake catalog migration are disabled after explicit provisioning", "Offline or incompatible extension installation fails before task dispatch", "Preflight proves Docker socket access, digest-pinned image pull, disposable container run, and sufficient workspace, image, and volume disk before task dispatch", "The receipt binds Python, platform, lockfile, DuckDB, Quack, DuckLake, provider binaries, repository tree and creation command"),
        track="foundation",
        priority="P0",
    ),
    _task(
        "DQK-083", "DQK-G200", "Implement governed plan/runtime-generation rollover and writer fencing",
        "Implement the only supported path for accepting a revised goal/task graph or attested runtime environment: drain and identify the current generation, verify signed and CID-bound DuckDB plan-revision/proposal and candidate-environment rows, materialize a new immutable DuckDB generation when requested, carry forward accepted terminal receipts, rotate plan/root/execution-slice/environment bindings and writer fences, then launch and verify the new master before retiring the old generation. Files may transport a revision or environment receipt but never become its authority. Completing this implementation task does not itself activate either generation.",
        depends_on=("DQK-007", "DQK-056", "DQK-080", "DQK-082"),
        outputs=("ipfs_datasets_py/duckdb_control/generation_rollover.py", "scripts/ops/ipfs_datasets_duckdb_quack_lifecycle.py", "tests/integration/test_duckdb_plan_generation_rollover.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_plan_generation_rollover.py",),
        acceptance=("A changed plan is never materialized over the active database", "Completing DQK-083 only installs the lifecycle owner; it cannot stand in for DQK-103 runtime activation or DQK-081 plan approval", "The lifecycle command consumes accepted signed/CID-bound DuckDB plan-revision and environment-generation rows independently of this seed TASKS tuple and refuses unapproved aliases or artifacts", "JSON/Markdown/formal-source/environment files are transport projections only and cannot authorize rollover", "Old-generation writers and daemons are fenced before new tasks become ready", "Static execution slices, exact source roots, sealed interpreter, extension profile, and environment digest are regenerated from the accepted revision and the new master is identity-bound", "Crash injection at every drain/materialize/launch/retire boundary is idempotently recoverable", "Restart after prior task merges verifies completion and merge receipts rather than requiring seed HEAD", "The rollover receipt binds old/new roots, database and environment identities, task population, writer epochs, process birth identities and signed authorization"),
        track="supervisor",
        priority="P0",
    ),
    _task(
        "DQK-103", "DQK-G200", "Activate the attested DuckDB, Quack, and DuckLake runtime generation",
        "Have a non-provider lifecycle owner running outside the old master/supervisor/daemon process tree verify the exact DQK-082 candidate-environment receipt, durably journal its own process-birth identity and intended effects before drain, acquire the program lifecycle and repository leases, drain the current master and workers, fence old task-source writers, invoke the DQK-083 rollover command without changing the accepted task population, relaunch every master/lane/daemon under the sealed attested interpreter and extension profile, verify process-birth argv/environment/capability evidence, and CAS-complete this gate only after bounded rollback and crash-replay checks pass. A fresh owner process must be able to authenticate and adopt an incomplete journal after the original owner dies.",
        depends_on=("DQK-082", "DQK-083"),
        outputs=(),
        validations=("python scripts/ops/ipfs_datasets_duckdb_quack_lifecycle.py activate-runtime --check",),
        acceptance=("A provider or implementation-task completion cannot activate a runtime generation", "The lifecycle owner runs outside the process tree it drains and writes a durable pre-drain journal binding its process-birth identity, operation permit, expected effects, source generation, and recovery owner", "A fresh authorized owner can authenticate and adopt the exact incomplete journal after process or host restart without repeating a committed effect", "The owner verifies the exact environment receipt, lock/artifact hashes, repository tree, task-source generation, caller process birth, operation permit, lease, and writer fence before drain", "Old masters, lanes, daemons, and DuckDB writers are quiesced and fenced before the new generation starts", "Every relaunched process is identity-bound to the sealed interpreter, exact extension profile, scrubbed environment, plan/repository roots, execution slice, state roots, and launch nonce", "A content-addressed activation receipt is stored in DuckDB and binds the owner/recovery journal, before/after process identities, environment generations, writer epochs, capability checks, and rollback window", "Crash injection at drain, fence, launch, verification, and acknowledgement boundaries replays idempotently without two live generations", "Only the dedicated permit-bound runtime-activation acknowledgement can complete this gate"),
        track="supervisor",
        priority="P0",
        completion="manual",
        schedulable=False,
        initial_status="blocked",
        blocked_reason="runtime_environment_activation_pending",
        authority_effect=MANUAL_GATE_AUTHORITY_EFFECT_IDS[RUNTIME_ACTIVATION_GATE_TASK_ID],
    ),
    _task(
        "DQK-006", "DQK-G100", "Expose schema, migration, integrity, and snapshot CLI",
        "Add a fail-closed operational CLI for create, migrate, inspect, check, snapshot, and capability status without accepting arbitrary SQL.",
        depends_on=("DQK-003", "DQK-004", "DQK-005"),
        outputs=("ipfs_datasets_py/duckdb_control/cli.py", "tests/cli/test_duckdb_control_cli.py"),
        validations=("python -m pytest -q tests/cli/test_duckdb_control_cli.py",),
        acceptance=("Every mutating command is idempotent and receipted", "Dry-run produces no database change", "CLI output has bounded text and structured modes"),
        track="foundation",
    ),
    _task(
        "DQK-007", "DQK-G200", "Bridge and harden canonical DuckDB task-source lifecycle through the supervisor",
        "Propagate task-source kind, sealed Python, and exact plan/repository roots through every supervisor layer; fence Markdown-only mutation; serialize local readers/writers; provide atomic consistent projections, durable post-merge evidence, authoritative completion evidence, and a governed quiescent retry/reset operation before launching this plan.",
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/merge_train.py", "ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/todo_daemon/implementation_supervisor.py", "ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/todo_daemon/implementation_daemon.py", "ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_task_source.py", "ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_retry_reset.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_implementation_daemon_runner.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_task_source_e2e.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_task_source.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_completion_evidence.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_retry_reset.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_merge_evidence_e2e.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_implementation_daemon_runner.py test/api/test_agent_supervisor_task_source_e2e.py test/api/test_agent_supervisor_duckdb_task_source.py test/api/test_agent_supervisor_duckdb_completion_evidence.py test/api/test_agent_supervisor_duckdb_retry_reset.py test/api/test_agent_supervisor_duckdb_merge_evidence_e2e.py",),
        acceptance=("The managed child command binds DuckDB source kind, both roots, and the sealed interpreter", "Invalid UTF-8 DuckDB bytes cannot be read, renamed, or replaced as Markdown", "All local file opens share one bounded process lock and exports read one transaction", "An exact two-parent merge publishes a fsynced content-addressed receipt before task CAS and fresh-daemon replay never moves the target twice", "Completion CAS carries exact validation/merge/lease/fence evidence", "Retry/reset is operation-authorized, idempotent, quiescent, all-lane, exact-source bound and durably receipted", "Bundles and compound submodule integrations fail closed until typed member receipts exist", "Legacy Markdown behavior remains compatible"),
        track="supervisor",
        priority="P0",
    ),
    _task(
        "DQK-015", "DQK-G300", "Port the knowledge graph catalog from SQLite to DuckDB",
        "Reimplement graph/branch/revision/lease/idempotency/pin/tombstone metadata with the existing branch-head CAS and lease semantics, migrations, and differential tests.",
        depends_on=("DQK-003", "DQK-004", "DQK-005"),
        outputs=("ipfs_datasets_py/knowledge_graphs/catalog/duckdb_store.py", "tests/unit/knowledge_graphs/test_duckdb_catalog_store.py"),
        validations=("python -m pytest -q tests/unit/knowledge_graphs/test_duckdb_catalog_store.py",),
        acceptance=("SQLite and DuckDB traces have equivalent results", "Branch CAS conflicts fail without partial mutation", "Pins, leases, tombstones, and idempotency survive restart"),
        track="knowledge-graph",
    ),
    _task(
        "DQK-016", "DQK-G300", "Project graph revisions and Parquet/IPLD segments into typed views",
        "Define normalized vertex, edge, property, adjacency, provenance, segment, and lineage tables while preserving immutable Parquet/IPLD bytes, checksums, CIDs, staging, and success markers.",
        depends_on=("DQK-004", "DQK-015"),
        outputs=("ipfs_datasets_py/knowledge_graphs/storage/duckdb_projection.py", "tests/unit/knowledge_graphs/test_duckdb_projection.py"),
        validations=("python -m pytest -q tests/unit/knowledge_graphs/test_duckdb_projection.py",),
        acceptance=("Large graph data is scanned from immutable segments rather than duplicated blindly", "Predicate pushdown works", "Projection rows bind exact graph revision and source CID"),
        track="knowledge-graph",
    ),
    _task(
        "DQK-017", "DQK-G300", "Persist graph transaction, MVCC, and WAL control state",
        "Move process-local active transaction and MVCC metadata into fenced DuckDB state while retaining the immutable IPLD WAL chain and idempotent recovery.",
        depends_on=("DQK-015", "DQK-016"),
        outputs=("ipfs_datasets_py/knowledge_graphs/transactions/duckdb_state.py", "tests/unit/knowledge_graphs/test_duckdb_transaction_state.py"),
        validations=("python -m pytest -q tests/unit/knowledge_graphs/test_duckdb_transaction_state.py",),
        acceptance=("Crash recovery neither loses nor duplicates committed revisions", "Stale transaction owners are fenced", "WAL CIDs remain unchanged"),
        track="knowledge-graph",
    ),
    _task(
        "DQK-018", "DQK-G300", "Integrate Cypher IR and recursive SQL query execution",
        "Compile supported Cypher/IR patterns to bounded parameterized DuckDB SQL and recursive CTEs, with fallback to the existing graph engine and result parity tests.",
        depends_on=("DQK-016", "DQK-017"),
        outputs=("ipfs_datasets_py/knowledge_graphs/core/duckdb_query_executor.py", "tests/unit/knowledge_graphs/test_duckdb_query_executor.py"),
        validations=("python -m pytest -q tests/unit/knowledge_graphs/test_duckdb_query_executor.py",),
        acceptance=("Supported queries are injection safe", "Traversal depth/rows/time are bounded", "Fallback and SQL results agree on conformance fixtures"),
        track="knowledge-graph",
    ),
    _task(
        "DQK-019", "DQK-G300", "Implement durable crypto-flow graph snapshots",
        "Add a DuckDB snapshot store for observed/asserted planes, ambiguity, retractions, reorgs, and immutable snapshot identities, replacing the in-memory-only store.",
        depends_on=("DQK-016", "DQK-017"),
        outputs=("ipfs_datasets_py/knowledge_graphs/crypto_flows/duckdb_store.py", "tests/unit/knowledge_graphs/test_crypto_flow_duckdb_store.py"),
        validations=("python -m pytest -q tests/unit/knowledge_graphs/test_crypto_flow_duckdb_store.py",),
        acceptance=("Snapshot identity is deterministic", "Reorg and retraction history is retained", "Concurrent readers never observe partial snapshots"),
        track="knowledge-graph",
    ),
    _task(
        "DQK-020", "DQK-G400", "Implement typed vector collection and lifecycle schema",
        "Add a DuckDB vector store with collection/model/chunk/generation/shard/tombstone/compaction metadata, exact dimension and dtype contracts, normalized source identities, and no pickle authority.",
        depends_on=("DQK-003", "DQK-004", "DQK-005"),
        outputs=("ipfs_datasets_py/vector_stores/duckdb_store.py", "tests/unit/vector_stores/test_duckdb_store.py"),
        validations=("python -m pytest -q tests/unit/vector_stores/test_duckdb_store.py",),
        acceptance=("Update/delete cannot leave query-visible stale vectors", "Model/chunking/normalization identity is mandatory", "Generations publish atomically"),
        track="vectors",
    ),
    _task(
        "DQK-021", "DQK-G400", "Add exact SQL vector search and dimension-specific physical tables",
        "Store authoritative FLOAT[N] vectors in dimension-specific tables, implement exact distance/ranking/filtering, and bind results to collection generation and content digest.",
        depends_on=("DQK-020",),
        outputs=("ipfs_datasets_py/vector_stores/duckdb_exact.py", "tests/unit/vector_stores/test_duckdb_exact.py"),
        validations=("python -m pytest -q tests/unit/vector_stores/test_duckdb_exact.py",),
        acceptance=("Exact results agree with NumPy fixtures", "Mixed dimensions cannot enter one physical table", "Metadata filters and deterministic tie-breaking are covered"),
        track="vectors",
    ),
    _task(
        "DQK-022", "DQK-G400", "Add capability-gated rebuildable VSS indexes",
        "Integrate pinned DuckDB VSS/HNSW as a derived acceleration layer with build receipts, health checks, tombstone/compaction policy, exact-search fallback, and corruption-safe rebuild.",
        depends_on=("DQK-002", "DQK-021"),
        outputs=("ipfs_datasets_py/vector_stores/duckdb_vss.py", "tests/unit/vector_stores/test_duckdb_vss.py"),
        validations=("python -m pytest -q tests/unit/vector_stores/test_duckdb_vss.py",),
        acceptance=("VSS is never the identity authority", "Missing/failed extension falls back safely", "Recall and tombstone parity thresholds are explicit"),
        track="vectors",
    ),
    _task(
        "DQK-023", "DQK-G400", "Migrate FAISS metadata and retain external vector adapters",
        "Import unsafe pickle metadata in an isolated one-time path, validate vectors/mappings, quarantine stale duplicates, and dual-read/write FAISS, Qdrant, and Elasticsearch during shadow mode.",
        depends_on=("DQK-020", "DQK-021"),
        outputs=("ipfs_datasets_py/vector_stores/duckdb_migration.py", "tests/unit/vector_stores/test_duckdb_migration.py"),
        validations=("python -m pytest -q tests/unit/vector_stores/test_duckdb_migration.py",),
        acceptance=("Normal runtime never unpickles", "Every imported generation has a source digest and reject report", "External backend parity is measured before promotion"),
        track="vectors",
    ),
    _task(
        "DQK-024", "DQK-G400", "Unify hybrid graph, vector, and full-text retrieval",
        "Create a bounded query API that combines graph predicates, exact/approximate vectors, text ranking, provenance, and revision filters without intermediate JSON serialization.",
        depends_on=("DQK-018", "DQK-021", "DQK-022", "DQK-023"),
        outputs=("ipfs_datasets_py/knowledge_graphs/query/duckdb_hybrid_search.py", "tests/unit/knowledge_graphs/test_duckdb_hybrid_search.py"),
        validations=("python -m pytest -q tests/unit/knowledge_graphs/test_duckdb_hybrid_search.py",),
        acceptance=("Results bind graph and vector generations", "Query budgets prevent control-plane starvation", "Legacy hybrid results meet declared differential thresholds"),
        track="vectors",
    ),
    _task(
        "DQK-025", "DQK-G500", "Define the unified proof cache schema and protocol",
        "Normalize proof keys, premises, translator/solver/toolchain/theorem-registry/policy/resource dimensions, outcomes, trust levels, evidence, access statistics, and immutable envelope references behind the existing verification cache protocol.",
        depends_on=("DQK-003", "DQK-004", "DQK-005"),
        outputs=("ipfs_datasets_py/logic/common/duckdb_proof_store.py", "tests/unit/logic/test_duckdb_proof_store.py"),
        validations=("python -m pytest -q tests/unit/logic/test_duckdb_proof_store.py",),
        acceptance=("No existing authority dimension is dropped", "Proof/counterexample/unknown/error outcomes remain distinct", "Exact key and integrity checks fail closed"),
        track="proofs",
    ),
    _task(
        "DQK-026", "DQK-G500", "Import fragmented JSON proof caches with parity receipts",
        "Build streaming adapters for common, TDFOL, CEC, integration, hammers, legal IR, and external prover caches with original-byte digests, rejects, TTL/trust translation, and differential reads.",
        depends_on=("DQK-001", "DQK-025"),
        outputs=("ipfs_datasets_py/logic/common/duckdb_proof_migration.py", "tests/unit/logic/test_duckdb_proof_migration.py"),
        validations=("python -m pytest -q tests/unit/logic/test_duckdb_proof_migration.py",),
        acceptance=("Imports are idempotent and bounded", "Ambiguous key/TTL/trust mappings quarantine rather than guess", "Whole-file JSON rewrites cease after promotion"),
        track="proofs",
    ),
    _task(
        "DQK-027", "DQK-G500", "Unify proof single-flight, leases, expiry, and invalidation",
        "Adapt existing formal verification/evidence stores into a common fenced single-flight coordinator with dual TTL, negative caching policy, invalidation, attempt records, and stale-publication rejection.",
        depends_on=("DQK-025", "DQK-056"),
        outputs=("ipfs_datasets_py/logic/common/duckdb_proof_coordination.py", "tests/unit/logic/test_duckdb_proof_coordination.py"),
        validations=("python -m pytest -q tests/unit/logic/test_duckdb_proof_coordination.py",),
        acceptance=("At most one valid producer publishes per proof key", "Expired fence publication is rejected", "Waiters recover after producer crash without duplicate authority"),
        track="proofs",
    ),
    _task(
        "DQK-028", "DQK-G500", "Project proof corpus envelopes, attestations, and revocations",
        "Index immutable proof-corpus manifests/envelopes/revocations/attestations by verified CID while leaving identity-bearing canonical bytes in content-addressed storage.",
        depends_on=("DQK-025", "DQK-026"),
        outputs=("ipfs_datasets_py/logic/proof_corpus/duckdb_repository.py", "tests/unit/logic/test_proof_corpus_duckdb_repository.py"),
        validations=("python -m pytest -q tests/unit/logic/test_proof_corpus_duckdb_repository.py",),
        acceptance=("Envelope bytes and CIDs remain unchanged", "Revoked or contradicted evidence is excluded from authoritative hits", "Tampered objects fail closed"),
        track="proofs",
    ),
    _task(
        "DQK-029", "DQK-G500", "Integrate proof schedulers and formal verification caches",
        "Make proof plans, nodes, attempts, leases, evidence receipts, draft/attested entries, and policy gates share the unified protocol without collapsing logic-specific semantics.",
        depends_on=("DQK-027", "DQK-028"),
        outputs=("ipfs_datasets_py/logic/common/duckdb_proof_service.py", "tests/integration/logic/test_duckdb_proof_service.py"),
        validations=("python -m pytest -q tests/integration/logic/test_duckdb_proof_service.py",),
        acceptance=("Existing proof scheduler traces replay", "Authority upgrades require evidence", "Logic-family adapters preserve their reviewed keys and fallback policies"),
        track="proofs",
    ),
    _task(
        "DQK-030", "DQK-G500", "Expose bounded proof, graph, and applicability joins",
        "Add query templates for proof hits/misses, premises, dependency closure, graph entities, source revisions, applicability, revocation, and counterexamples with explicit authority and freshness columns.",
        depends_on=("DQK-018", "DQK-029"),
        outputs=("ipfs_datasets_py/logic/common/duckdb_proof_queries.py", "tests/unit/logic/test_duckdb_proof_queries.py"),
        validations=("python -m pytest -q tests/unit/logic/test_duckdb_proof_queries.py",),
        acceptance=("Queries cannot promote an untrusted cache hit", "Freshness/applicability/revocation are always visible", "Recursive premise traversal is bounded"),
        track="proofs",
    ),
    _task(
        "DQK-031", "DQK-G600", "Define normalized AST and code-evidence schema",
        "Reuse the supervisor code-evidence projection and map canonical software-contract AST IR into source revisions, files, blobs, nodes, spans, scopes, symbols, imports, references, calls, effects, interfaces, diagnostics, and invalidations.",
        depends_on=("DQK-003", "DQK-004", "DQK-005"),
        outputs=("ipfs_datasets_py/logic/software_contracts/duckdb_ast_store.py", "tests/unit/logic/software_contracts/test_duckdb_ast_store.py"),
        validations=("python -m pytest -q tests/unit/logic/software_contracts/test_duckdb_ast_store.py",),
        acceptance=("Canonical AST IR identity and source spans survive projection", "Datasets and supervisor do not invent incompatible AST schemas", "Parse failures are durable queryable facts"),
        track="ast",
    ),
    _task(
        "DQK-032", "DQK-G600", "Implement incremental Python/TypeScript AST ingestion",
        "Ingest tracked Git source revisions, reuse unchanged shards by CID, invalidate changed files/symbols/edges, and publish a complete revision atomically.",
        depends_on=("DQK-031",),
        outputs=("ipfs_datasets_py/logic/software_contracts/duckdb_ingest.py", "tests/unit/logic/software_contracts/test_duckdb_ingest.py"),
        validations=("python -m pytest -q tests/unit/logic/software_contracts/test_duckdb_ingest.py",),
        acceptance=("Unchanged source is not reparsed", "Deleted/renamed symbols cannot leak from older revisions", "Dirty-tree policy and Git object identity are explicit"),
        track="ast",
    ),
    _task(
        "DQK-033", "DQK-G600", "Add AST impact, conflict, and dependency queries",
        "Implement bounded reverse-reference, call, import, effect, interface, semantic-dependency, and conflict closure queries used for task scopes, validation selection, and proof invalidation.",
        depends_on=("DQK-032",),
        outputs=("ipfs_datasets_py/logic/software_contracts/duckdb_impact.py", "tests/unit/logic/software_contracts/test_duckdb_impact.py"),
        validations=("python -m pytest -q tests/unit/logic/software_contracts/test_duckdb_impact.py",),
        acceptance=("Closures bind an exact source revision", "Depth/row/time budgets are enforced", "Known impact fixtures agree with existing analyzers"),
        track="ast",
    ),
    _task(
        "DQK-034", "DQK-G600", "Consume the supervisor AST and code-evidence release plane",
        "Adapt datasets code-evidence consumers to the DQP-039 revision-bound AST, dependency, conflict, and evidence interfaces without reimplementing the supervisor stores.",
        depends_on=("DQK-031", "DQK-033", "DQK-056"),
        outputs=("ipfs_datasets_py/knowledge_graphs/adapters/duckdb_code_evidence.py", "tests/unit/knowledge_graphs/test_duckdb_code_evidence.py"),
        validations=("python -m pytest -q tests/unit/knowledge_graphs/test_duckdb_code_evidence.py",),
        acceptance=("The adapter verifies the exact DQP release/tree/schema identity", "No whole-artifact JSON load is required", "Datasets and supervisor projections remain schema compatible"),
        track="ast",
    ),
    _task(
        "DQK-035", "DQK-G700", "Define privacy-safe normalized wallet ledger schema",
        "Map chain/account/asset/block/transaction/transfer/UTXO/token-account/contract-event/cursor/checkpoint/finality/reorg models to strict typed tables with exact amount strings and public-data classification.",
        depends_on=("DQK-003", "DQK-004", "DQK-005"),
        outputs=("ipfs_datasets_py/processors/wallets/duckdb_schema.py", "tests/unit/processors/wallets/test_duckdb_schema.py"),
        validations=("python -m pytest -q tests/unit/processors/wallets/test_duckdb_schema.py",),
        acceptance=("No float coercion of monetary amounts", "Every row binds chain/source/finality", "Secret-bearing fields and raw payloads are absent from query-visible tables"),
        track="wallet",
    ),
    _task(
        "DQK-036", "DQK-G700", "Implement transactional wallet store and durable checkpoints",
        "Replace in-memory staging/checkpoint authority with idempotent batches, CAS checkpoints, finality transitions, reorg rollback/replay, and CID references to encrypted/raw objects.",
        depends_on=("DQK-035",),
        outputs=("ipfs_datasets_py/processors/wallets/duckdb_storage.py", "tests/unit/processors/wallets/test_duckdb_storage.py"),
        validations=("python -m pytest -q tests/unit/processors/wallets/test_duckdb_storage.py",),
        acceptance=("Crash recovery cannot skip or duplicate ledger records", "Checkpoint CAS rejects stale ingesters", "Reorg history is retained instead of overwritten"),
        track="wallet",
    ),
    _task(
        "DQK-037", "DQK-G700", "Import JSONL wallet records and produce typed Parquet exports",
        "Stream legacy records.jsonl, metadata sidecars, and opaque payload_json Parquet into validated rows and export typed partitions plus bounded extension fields and deterministic manifests.",
        depends_on=("DQK-001", "DQK-035", "DQK-036"),
        outputs=("ipfs_datasets_py/processors/wallets/duckdb_migration.py", "tests/unit/processors/wallets/test_duckdb_migration.py"),
        validations=("python -m pytest -q tests/unit/processors/wallets/test_duckdb_migration.py",),
        acceptance=("Imports retain original digests and rejects", "Typed exports support predicate pushdown", "JSON manifests are generated outputs, never authority"),
        track="wallet",
    ),
    _task(
        "DQK-038", "DQK-G700", "Project wallet records into crypto-flow graph revisions",
        "Incrementally derive observed/asserted crypto-flow nodes and edges from normalized transactions while preserving ambiguity, retractions, finality, and reorg lineage.",
        depends_on=("DQK-019", "DQK-036"),
        outputs=("ipfs_datasets_py/processors/wallets/duckdb_graph_projection.py", "tests/unit/processors/wallets/test_duckdb_graph_projection.py"),
        validations=("python -m pytest -q tests/unit/processors/wallets/test_duckdb_graph_projection.py",),
        acceptance=("Projection is idempotent by ledger and graph revision", "Reorgs retract rather than silently mutate history", "Asserted and observed planes cannot be confused"),
        track="wallet",
    ),
    _task(
        "DQK-039", "DQK-G700", "Add wallet/proof/AST joins and secret-surface gates",
        "Provide allowlisted queries connecting transactions, contracts, source symbols, graph flows, and verification evidence, with secret scanning, column classification, and row/tenant policy enforcement.",
        depends_on=("DQK-029", "DQK-033", "DQK-038"),
        outputs=("ipfs_datasets_py/processors/wallets/duckdb_queries.py", "tests/unit/processors/wallets/test_duckdb_queries.py"),
        validations=("python -m pytest -q tests/unit/processors/wallets/test_duckdb_queries.py",),
        acceptance=("Private keys/seeds/signing payloads are rejected", "Queries expose authority and finality", "Cross-domain joins obey tenant and resource budgets"),
        track="wallet",
    ),
    _task(
        "DQK-040", "DQK-G800", "Implement workload-separated catalog federation",
        "Federate authority catalogs only inside a trusted in-process query broker, using explicit workload routes and sanitized copy-out publications so expensive scans cannot hold the control writer or expose sensitive catalogs to Quack clients.",
        depends_on=("DQK-005", "DQK-016", "DQK-020", "DQK-025", "DQK-031", "DQK-035", "DQK-056", "DQK-082", "DQK-103"),
        outputs=("ipfs_datasets_py/duckdb_control/federation.py", "tests/integration/test_duckdb_catalog_federation.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_catalog_federation.py",),
        acceptance=("No GRANT-style catalog ACL is assumed", "Untrusted sessions never ATTACH authority catalogs", "Cross-catalog snapshots expose revision bindings", "Analytical cancellation leaves control-plane transactions healthy"),
        track="query",
    ),
    _task(
        "DQK-041", "DQK-G800", "Build allowlisted query-template registry and budgets",
        "Replace arbitrary SQL exposure with versioned parameter schemas, prepared templates, tenant/column policy, row/byte/time/depth limits, cancellation, audit, and deterministic query receipts.",
        depends_on=("DQK-004", "DQK-005", "DQK-040"),
        outputs=("ipfs_datasets_py/duckdb_control/query_registry.py", "tests/unit/duckdb_control/test_query_registry.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_query_registry.py",),
        acceptance=("Untrusted callers cannot submit arbitrary SQL", "read_* functions and extension/filesystem/network surfaces are denied", "Receipts identify template, parameters digest, snapshot, policy, and resource usage"),
        track="query",
    ),
    _task(
        "DQK-042", "DQK-G800", "Execute cross-domain queries in parallel with backpressure",
        "Add a scheduler that runs independent graph/vector/proof/AST/wallet subqueries concurrently, propagates deadlines/cancellation, joins bounded results, and reserves control-plane capacity.",
        depends_on=("DQK-024", "DQK-030", "DQK-034", "DQK-039", "DQK-041"),
        outputs=("ipfs_datasets_py/duckdb_control/parallel_query.py", "tests/integration/test_duckdb_parallel_query.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_parallel_query.py",),
        acceptance=("Independent subqueries actually overlap", "Partial timeout/failure is typed", "Lease heartbeat p99 stays within SLO under benchmark load"),
        track="query",
    ),
    _task(
        "DQK-043", "DQK-G800", "Expose safe CLI and MCP query/export endpoints",
        "Integrate the allowlisted registry with datasets CLI/MCP tools for query, explain, export, status, and cancellation, binding callers to capabilities and snapshots.",
        depends_on=("DQK-006", "DQK-041", "DQK-042", "DQK-058"),
        outputs=("ipfs_datasets_py/mcp_server/tools/duckdb_query_tools.py", "tests/mcp/test_duckdb_query_tools.py"),
        validations=("python -m pytest -q tests/mcp/test_duckdb_query_tools.py",),
        acceptance=("Endpoints cannot bypass the query registry", "Cancellation and bounded pagination work", "Errors do not leak secrets, raw SQL, or tokens"),
        track="query",
    ),
    _task(
        "DQK-044", "DQK-G900", "Build the streaming legacy artifact importer",
        "Import JSON/JSONL/Markdown taskboards/SQLite/Parquet/vector metadata and manifests through type-specific bounded batches, source digests, resumable cursors, reject tables, and idempotency keys.",
        depends_on=("DQK-001", "DQK-003", "DQK-004"),
        outputs=("ipfs_datasets_py/duckdb_control/importer.py", "tests/unit/duckdb_control/test_importer.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_importer.py",),
        acceptance=("Interrupted imports resume exactly", "Original byte digests and line/record provenance are retained", "Exports are never silently re-imported"),
        track="migration",
    ),
    _task(
        "DQK-045", "DQK-G900", "Implement deterministic Markdown, JSON, Parquet, Arrow, and CAR exports",
        "Make exports explicit read-only jobs with query/template ID, parameters digest, schema version, snapshot/revision, root CID, content digest, destination policy, and replay verification.",
        depends_on=("DQK-004", "DQK-006", "DQK-041"),
        outputs=("ipfs_datasets_py/duckdb_control/exporter.py", "tests/unit/duckdb_control/test_exporter.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_exporter.py",),
        acceptance=("Repeated export of one snapshot is byte-identical", "An export cannot mutate or become implicit authority", "Sensitive columns are excluded by policy"),
        track="migration",
    ),
    _task(
        "DQK-046", "DQK-G900", "Implement shadow reads, dual writes, parity, and quarantine",
        "Install one domain-neutral authority-transition port in the existing datasets database factories, with legacy/shadow/dual/db-primary/export-only modes, transactional outbox recovery, parity receipts, disagreement quarantine, and explicit promotion/rollback decisions.",
        depends_on=("DQK-002", "DQK-003", "DQK-004", "DQK-044", "DQK-045", "DQK-081"),
        outputs=("ipfs_datasets_py/duckdb_control/authority_transition.py", "ipfs_datasets_py/database_utils.py", "requirements.txt", "pyproject.toml", "__pyproject.toml", "setup.py", "tests/integration/test_duckdb_authority_transition.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_authority_transition.py",),
        acceptance=("Crash before or after each DB/outbox boundary recovers idempotently", "Mismatch never silently promotes", "Promotion and rollback are CAS-protected, fenced, and receipted", "No implementation claims cross-filesystem atomicity", "All package metadata agrees on the pinned DuckDB compatibility window"),
        track="migration",
    ),
    _task(
        "DQK-047", "DQK-G900", "Add checkpoint, backup, restore, compaction, and retention operations",
        "Provide workload-aware checkpoint/backup/restore/verify/compact/retention workflows for DuckDB files and referenced immutable objects, with quiescence/fencing and disaster receipts.",
        depends_on=("DQK-003", "DQK-005", "DQK-046"),
        outputs=("ipfs_datasets_py/duckdb_control/recovery.py", "tests/integration/test_duckdb_recovery.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_recovery.py",),
        acceptance=("Restore proves schema and snapshot digests", "Retention cannot delete referenced evidence", "Recovery does not rely on cross-database atomicity"),
        track="migration",
    ),
    _task(
        "DQK-048", "DQK-G900", "Benchmark and soak the 970 MB production-hardening corpus",
        "Run bounded streaming migration, event/receipt query, backup/restore, and concurrency benchmarks against the real production-hardening fixture with memory, disk, time, lock, and parity metrics.",
        depends_on=("DQK-044", "DQK-047", "DQK-056", "DQK-082", "DQK-103"),
        outputs=("benchmarks/duckdb_quack_migration_benchmark.py", "tests/benchmarks/test_duckdb_quack_migration_benchmark.py"),
        validations=("python -m pytest -q tests/benchmarks/test_duckdb_quack_migration_benchmark.py",),
        acceptance=("Benchmark is resumable and does not mutate the fixture", "Peak memory and transaction latency stay within declared budgets", "Every migrated population has count and digest parity receipts"),
        track="migration",
        priority="P2",
    ),
    _task(
        "DQK-049", "DQK-G1000", "Harden Quack authentication, authorization, TLS, and process isolation",
        "Create a Quack threat model and guarded server launcher with two explicit profiles. Sanitized publication gateways use loopback defaults, per-operation credentials, restricted OS identity, disabled external access, query authorization, audit, and a supported TLS reverse proxy. Internal DuckLake catalog owners deny by default but pre-load only pinned DuckLake/Quack/object extensions, restrict local paths/filesystems, permit egress only to the shard's exact object endpoint or TLS proxy, and install non-default fresh-connection authentication plus exact full-SQL authorization callbacks. Neither profile inherits ambient filesystem, extension, secret, or network reachability.",
        depends_on=("DQK-002", "DQK-005", "DQK-041", "DQK-056", "DQK-082", "DQK-103"),
        outputs=("ipfs_datasets_py/duckdb_control/quack_security.py", "tests/security/test_quack_security.py"),
        validations=("python -m pytest -q tests/security/test_quack_security.py",),
        acceptance=("Default authentication and authorization are never permissive for agent traffic", "Fresh catalog-owner connections require a one-use operation capability through a non-default authentication callback or authenticating proxy", "Publication and catalog-owner profiles have distinct external-access, extension, local-path, filesystem, and egress policies", "A catalog owner can reach only its exact local catalog path and selected object endpoint/TLS proxy; a publication gateway reaches neither", "Remote plaintext exposure is rejected", "Tokens and full SQL text are handled as sensitive"),
        track="security",
    ),
    _task(
        "DQK-050", "DQK-G1000", "Create Quack protocol and upgrade compatibility suite",
        "Test local/stateless/attached sessions, transactions, large fetches, known attached UPDATE/DELETE and ALTER gaps, rollback behavior, crashed-client resource cleanup, fresh-connection authentication hooks, exact full-SQL authorization, extension pinning, and upgrade refusal against the exact DQK-084 DuckLake capability profile. Add a DuckLake-over-Quack contract slice proving one server-owned DuckDB catalog can serve concurrent remote snapshot readers without shared-session drift, one authorized remote mutation reports the expected last committed snapshot, cancellation/lost fetch releases server state, prepared parameters remain separate from the exact authorization template, and internal DuckLake metadata/file-key functions plus SHOW/duckdb_*, SET/RESET/PRAGMA/COPY/read_*/network surfaces remain unreachable.",
        depends_on=("DQK-002", "DQK-049", "DQK-056", "DQK-058", "DQK-084"),
        outputs=("tests/compatibility/test_duckdb_quack_contract.py", "scripts/validation/validate_duckdb_quack_compatibility.py"),
        validations=("python -m pytest -q tests/compatibility/test_duckdb_quack_contract.py",),
        acceptance=("Known gaps have tested workarounds or hard gates", "DuckLake-over-Quack snapshot reads, mutations, cancellation, authentication, parameterization, and internal-surface denial pass before DQK-104", "Two remote readers selecting distinct snapshot versions cannot change each other's server session state", "Server/client/extension mismatch fails before mutation", "Quack beta use and DuckDB 2.0 adoption each require an explicit compatibility and risk/requalification receipt"),
        track="security",
    ),
    _task(
        "DQK-051", "DQK-G1000", "Add concurrency, crash, corruption, and stall chaos tests",
        "Inject failures at claim, heartbeat, proof publication, graph/vector/wallet batch, checkpoint, export, merge, backup, Quack response, and process death boundaries; prove bounded recovery and no duplicate authority.",
        depends_on=("DQK-027", "DQK-042", "DQK-046", "DQK-047", "DQK-050", "DQK-056"),
        outputs=("tests/chaos/test_duckdb_quack_control_plane.py", "scripts/validation/validate_duckdb_quack_chaos.py"),
        validations=("python -m pytest -q tests/chaos/test_duckdb_quack_control_plane.py",),
        acceptance=("Stale fences cannot publish", "No-progress and deadlock diagnoses are typed", "Recovery preserves dirty work and immutable evidence"),
        track="security",
    ),
    _task(
        "DQK-052", "DQK-G1000", "Unify observability, audit, traces, and query profiles",
        "Store lifecycle events, trace/span correlation, health samples, query profiles, blocker transitions, dead letters, and audit records in a typed append-only observability catalog with bounded retention/export.",
        depends_on=("DQK-041", "DQK-056"),
        outputs=("ipfs_datasets_py/duckdb_control/observability.py", "tests/unit/duckdb_control/test_observability.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_observability.py",),
        acceptance=("File mtimes are not progress authority", "Sensitive query text is redacted/classified", "Control, query, proof, graph, vector, AST, and wallet traces correlate by IDs"),
        track="security",
    ),
    _task(
        "DQK-057", "DQK-G200", "Implement the external DQP release verifier",
        "Implement the fail-closed JSON verifier invoked by `ack-release --receipt ...`: verify terminal DQP-039 DuckDBControlPlaneReleaseReceipt@1 joined to DQP-038 DatabaseCutoverReceipt@1, exact accelerator Git commit/tree, store generation, schema checksum, Quack compatibility profile, expiry, signature, and accepted decision, then emit the strict typed verification object consumed by the gate CAS.",
        depends_on=("DQK-007",),
        outputs=("scripts/validation/validate_accelerate_duckdb_quack_release.py", "tests/integration/test_accelerate_duckdb_quack_release.py"),
        validations=("python -m pytest -q tests/integration/test_accelerate_duckdb_quack_release.py",),
        acceptance=("CLI accepts --receipt, --accelerate-root and --json and emits ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1", "Markdown and process status cannot satisfy the gate", "Missing canonical receipt query or machine-readable identity fails closed", "A stale, mismatched, expired, unsigned, or unaccepted cutover receipt is rejected"),
        track="supervisor",
        priority="P0",
    ),
    _task(
        "DQK-056", "DQK-G200", "Pin the completed DQP supervisor control-plane release",
        "After DQP-039 completes, verify its canonical release/cutover receipt and update the datasets submodule gitlink to that exact accepted accelerator commit before admitting any supervisor-dependent cutover.",
        depends_on=("DQK-057",),
        outputs=("ipfs_accelerate_py",),
        validations=("python scripts/validation/validate_accelerate_duckdb_quack_release.py --check",),
        acceptance=("DQP-039 transitively covers DQP-001 through DQP-038", "The receipt binds exact Git tree, store generation, schema checksum, Quack profile, expiry, and accepted decision", "The parent gitlink and receipt identify the same commit", "An auditable revision-CAS changes this task directly from blocked to completed"),
        track="supervisor",
        priority="P0",
        completion="manual",
        schedulable=False,
        external_prerequisites=("agent-supervisor-duckdb-quack-control-plane-v1:DQP-039:DuckDBControlPlaneReleaseReceipt@1",),
        initial_status="blocked",
        blocked_reason="external_release_receipt_pending",
        authority_effect=MANUAL_GATE_AUTHORITY_EFFECT_IDS[RELEASE_GATE_TASK_ID],
    ),
    _task(
        "DQK-058", "DQK-G800", "Build a physically separate sanitized Quack publication plane",
        "Materialize fenced, revision-bound allowlisted read models into a separate DuckDB served read-only by Quack; the Quack process must never open or ATTACH control, proof, graph-writer, AST-writer, or wallet authority databases.",
        depends_on=("DQK-040", "DQK-041", "DQK-045", "DQK-049"),
        outputs=("ipfs_datasets_py/duckdb_control/publication.py", "tests/security/test_quack_publication_plane.py"),
        validations=("python -m pytest -q tests/security/test_quack_publication_plane.py",),
        acceptance=("Sensitive/internal tables and wallet raw columns are physically absent", "The broker retains authority tokens and clients receive no writer credential", "ATTACH, COPY, INSTALL, LOAD, CREATE SECRET, read_* and HTTP/S3 access fail", "Killing or overloading Quack cannot block authority writers"),
        track="query",
        priority="P0",
    ),
    _task(
        "DQK-059", "DQK-G300", "Integrate graph producers and run DuckDB shadow authority",
        "Route the existing graph catalog service, engine, transactions, storage, and crypto-flow snapshot producers through the authority port while SQLite/JSON remains authoritative and DuckDB emits parity receipts.",
        depends_on=("DQK-015", "DQK-016", "DQK-017", "DQK-018", "DQK-019", "DQK-046"),
        outputs=("ipfs_datasets_py/knowledge_graphs/catalog/store.py", "ipfs_datasets_py/knowledge_graphs/service.py", "ipfs_datasets_py/knowledge_graphs/core/graph_engine.py", "ipfs_datasets_py/knowledge_graphs/transactions/manager.py", "ipfs_datasets_py/knowledge_graphs/storage/hybrid.py", "ipfs_datasets_py/knowledge_graphs/crypto_flows/store.py", "tests/integration/knowledge_graphs/test_duckdb_shadow_authority.py"),
        validations=("python -m pytest -q tests/integration/knowledge_graphs/test_duckdb_shadow_authority.py",),
        acceptance=("Branch CAS, leases, pins, tombstones, WAL/MVCC, restart and crypto-flow histories have SQLite/DuckDB parity", "Every producer operation has an idempotent DB operation ID", "Parquet/IPLD bytes, checksums, and CIDs remain unchanged"),
        track="knowledge-graph",
    ),
    _task(
        "DQK-060", "DQK-G300", "Promote graph control metadata to DuckDB authority",
        "Run fenced dual writes and promote DuckDB as authority for graph catalog and transaction-control metadata while immutable Parquet/IPLD revisions remain the content authority.",
        depends_on=("DQK-024", "DQK-059"),
        outputs=("ipfs_datasets_py/knowledge_graphs/catalog/store.py", "ipfs_datasets_py/knowledge_graphs/client.py", "ipfs_datasets_py/knowledge_graphs/transactions/manager.py", "ipfs_datasets_py/knowledge_graphs/storage/hybrid.py", "tests/integration/knowledge_graphs/test_duckdb_authority_cutover.py"),
        validations=("python -m pytest -q tests/integration/knowledge_graphs/test_duckdb_authority_cutover.py",),
        acceptance=("No branch-head split brain or lost transaction under crash/restart", "Readers bind one revision during promotion", "Legacy writes are outbox projections and rollback is receipted"),
        track="knowledge-graph",
    ),
    _task(
        "DQK-061", "DQK-G300", "Remove SQLite and JSON graph-control authority",
        "Remove implicit SQLite fallback and mutable JSON control reads/writes from graph producers, retaining only explicit import/export compatibility and immutable identity-bearing manifests.",
        depends_on=("DQK-053", "DQK-058", "DQK-060"),
        outputs=("ipfs_datasets_py/knowledge_graphs/catalog/store.py", "ipfs_datasets_py/knowledge_graphs/service.py", "ipfs_datasets_py/knowledge_graphs/storage/hybrid.py", "tests/e2e/knowledge_graphs/test_duckdb_only_graph_control.py"),
        validations=("python -m pytest -q tests/e2e/knowledge_graphs/test_duckdb_only_graph_control.py",),
        acceptance=("Graph service starts from DuckDB plus immutable Parquet/IPLD with legacy catalog files absent", "Static and dynamic guards find no mutable graph-control file writer", "Only sanitized graph views reach the publication database"),
        track="knowledge-graph",
        priority="P0",
    ),
    _task(
        "DQK-062", "DQK-G400", "Integrate vector producers and run DuckDB metadata shadowing",
        "Route collection, model, chunk, mapping, generation, shard, tombstone, and build producers in the manager/API and FAISS/IPLD/Qdrant/Elasticsearch adapters through the DuckDB vector catalog.",
        depends_on=("DQK-020", "DQK-021", "DQK-022", "DQK-023", "DQK-046"),
        outputs=("ipfs_datasets_py/vector_stores/manager.py", "ipfs_datasets_py/vector_stores/management_engine.py", "ipfs_datasets_py/vector_stores/api.py", "ipfs_datasets_py/vector_stores/faiss_store.py", "ipfs_datasets_py/vector_stores/ipld_vector_store.py", "ipfs_datasets_py/vector_stores/ipld.py", "ipfs_datasets_py/vector_stores/qdrant_store.py", "ipfs_datasets_py/vector_stores/elasticsearch_store.py", "ipfs_datasets_py/embeddings/shard_embeddings_engine.py", "ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py", "ipfs_datasets_py/processors/storage/ipld/vector_store.py", "ipfs_datasets_py/mcp_server/tools/vector_tools/vector_store_management.py", "ipfs_datasets_py/mcp_server/tools/vector_tools/shared_state.py", "tests/integration/vector_stores/test_duckdb_shadow_catalog.py"),
        validations=("python -m pytest -q tests/integration/vector_stores/test_duckdb_shadow_catalog.py",),
        acceptance=("All adapters and MCP create/list/delete entrypoints have mapping/count/query parity across restart", "Dimension, dtype, model, chunking, normalization and source revision are exact", "metadata.json, shard manifests, IPFS KNN mappings and duplicate IPLD stores are covered", "Shadow failures quarantine without changing legacy authority"),
        track="vectors",
    ),
    _task(
        "DQK-063", "DQK-G400", "Promote vector lifecycle metadata to DuckDB authority",
        "Run dual mode and promote DuckDB collection/generation/tombstone/compaction metadata while vector bytes remain in the selected engine or immutable segment.",
        depends_on=("DQK-024", "DQK-062"),
        outputs=("ipfs_datasets_py/vector_stores/manager.py", "ipfs_datasets_py/vector_stores/management_engine.py", "ipfs_datasets_py/vector_stores/api.py", "ipfs_datasets_py/vector_stores/faiss_store.py", "ipfs_datasets_py/vector_stores/ipld_vector_store.py", "ipfs_datasets_py/vector_stores/ipld.py", "ipfs_datasets_py/vector_stores/qdrant_store.py", "ipfs_datasets_py/vector_stores/elasticsearch_store.py", "ipfs_datasets_py/embeddings/shard_embeddings_engine.py", "ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py", "ipfs_datasets_py/processors/storage/ipld/vector_store.py", "ipfs_datasets_py/mcp_server/tools/vector_tools/vector_store_management.py", "ipfs_datasets_py/mcp_server/tools/vector_tools/shared_state.py", "tests/integration/vector_stores/test_duckdb_authority_cutover.py"),
        validations=("python -m pytest -q tests/integration/vector_stores/test_duckdb_authority_cutover.py",),
        acceptance=("Update/delete cannot resurrect stale or duplicate live vectors", "External backend failures retry idempotently", "VSS remains derived and exact-search fallback stays available"),
        track="vectors",
    ),
    _task(
        "DQK-064", "DQK-G400", "Remove pickle and ad-hoc vector metadata authority",
        "Make FAISS pickle and process-local mappings one-time import compatibility only, with no silent fallback after DuckDB promotion.",
        depends_on=("DQK-053", "DQK-058", "DQK-063"),
        outputs=("ipfs_datasets_py/vector_stores/manager.py", "ipfs_datasets_py/vector_stores/management_engine.py", "ipfs_datasets_py/vector_stores/api.py", "ipfs_datasets_py/vector_stores/faiss_store.py", "ipfs_datasets_py/vector_stores/ipld_vector_store.py", "ipfs_datasets_py/vector_stores/ipld.py", "ipfs_datasets_py/embeddings/shard_embeddings_engine.py", "ipfs_datasets_py/ml/embeddings/ipfs_knn_index.py", "ipfs_datasets_py/processors/storage/ipld/vector_store.py", "ipfs_datasets_py/mcp_server/tools/vector_tools/vector_store_management.py", "ipfs_datasets_py/mcp_server/tools/vector_tools/shared_state.py", "tests/e2e/vector_stores/test_duckdb_only_vector_metadata.py"),
        validations=("python -m pytest -q tests/e2e/vector_stores/test_duckdb_only_vector_metadata.py",),
        acceptance=("Normal runtime never reads or writes *_metadata.pkl, vector_indexes/*/metadata.json, shard JSON, or mutable manifest JSON", "MCP and manager restart from DuckDB plus vector segments without process-local mapping loss", "Publication exposes approved collection/build statistics rather than unrestricted embeddings"),
        track="vectors",
        priority="P0",
    ),
    _task(
        "DQK-065", "DQK-G500", "Integrate all proof producers and run DuckDB shadowing",
        "Place every proof-cache lookup/write, single-flight claim, attempt, attestation, invalidation, and corpus-index mutation behind the unified repository while retaining each logic family's authority dimensions and immutable envelope bytes.",
        depends_on=("DQK-025", "DQK-026", "DQK-027", "DQK-028", "DQK-029", "DQK-046"),
        outputs=("ipfs_datasets_py/logic/common/proof_cache.py", "ipfs_datasets_py/logic/hammers/proof_cache.py", "ipfs_datasets_py/logic/legal_ir/proof_cache.py", "ipfs_datasets_py/logic/integration/proof_cache.py", "ipfs_datasets_py/logic/integration/caching/proof_cache.py", "ipfs_datasets_py/logic/integration/caching/ipfs_proof_cache.py", "ipfs_datasets_py/logic/external_provers/proof_cache.py", "ipfs_datasets_py/logic/TDFOL/tdfol_proof_cache.py", "ipfs_datasets_py/logic/CEC/native/cec_proof_cache.py", "ipfs_datasets_py/logic/CEC/optimization/formula_cache.py", "ipfs_datasets_py/logic/flogic/flogic_proof_cache.py", "ipfs_datasets_py/logic/security_ir/constraint_cache.py", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_cache.py", "tests/integration/logic/test_duckdb_proof_shadow.py"),
        validations=("python -m pytest -q tests/integration/logic/test_duckdb_proof_shadow.py",),
        acceptance=("No hit crosses incompatible solver/toolchain/premise/policy identities", "Trust mismatches fail closed", "Every legacy backend has differential receipts", "Proof envelope bytes and CIDs remain unchanged"),
        track="proof",
    ),
    _task(
        "DQK-066", "DQK-G500", "Promote proof cache and query state to DuckDB authority",
        "Run dual mode and promote mutable proof cache, index, single-flight, expiry, invalidation, revocation, access, and scheduler state to DuckDB.",
        depends_on=("DQK-030", "DQK-065"),
        outputs=("ipfs_datasets_py/logic/common/proof_cache.py", "ipfs_datasets_py/logic/hammers/proof_cache.py", "ipfs_datasets_py/logic/legal_ir/proof_cache.py", "ipfs_datasets_py/logic/integration/proof_cache.py", "ipfs_datasets_py/logic/integration/caching/proof_cache.py", "ipfs_datasets_py/logic/integration/caching/ipfs_proof_cache.py", "ipfs_datasets_py/logic/external_provers/proof_cache.py", "ipfs_datasets_py/logic/TDFOL/tdfol_proof_cache.py", "ipfs_datasets_py/logic/CEC/native/cec_proof_cache.py", "ipfs_datasets_py/logic/CEC/optimization/formula_cache.py", "ipfs_datasets_py/logic/flogic/flogic_proof_cache.py", "ipfs_datasets_py/logic/security_ir/constraint_cache.py", "ipfs_datasets_py/logic/proof_corpus/store.py", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_cache.py", "tests/integration/logic/test_duckdb_proof_authority.py"),
        validations=("python -m pytest -q tests/integration/logic/test_duckdb_proof_authority.py",),
        acceptance=("Concurrent single-flight, stale fence, expiry, revocation, tamper and restart tests pass", "The corpus index rebuilds from immutable envelopes", "No promoted operation rewrites a whole JSON cache"),
        track="proof",
    ),
    _task(
        "DQK-067", "DQK-G500", "Remove JSON proof cache and index authority",
        "Convert mutable JSON cache files and index.json into explicit import/export compatibility while immutable per-CID proof envelopes remain canonical evidence.",
        depends_on=("DQK-053", "DQK-058", "DQK-066"),
        outputs=("ipfs_datasets_py/logic/common/proof_cache.py", "ipfs_datasets_py/logic/hammers/proof_cache.py", "ipfs_datasets_py/logic/legal_ir/proof_cache.py", "ipfs_datasets_py/logic/integration/proof_cache.py", "ipfs_datasets_py/logic/integration/caching/proof_cache.py", "ipfs_datasets_py/logic/integration/caching/ipfs_proof_cache.py", "ipfs_datasets_py/logic/external_provers/proof_cache.py", "ipfs_datasets_py/logic/TDFOL/tdfol_proof_cache.py", "ipfs_datasets_py/logic/CEC/native/cec_proof_cache.py", "ipfs_datasets_py/logic/CEC/optimization/formula_cache.py", "ipfs_datasets_py/logic/flogic/flogic_proof_cache.py", "ipfs_datasets_py/logic/security_ir/constraint_cache.py", "ipfs_datasets_py/logic/proof_corpus/store.py", "ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_cache.py", "tests/e2e/logic/test_duckdb_only_proof_state.py"),
        validations=("python -m pytest -q tests/e2e/logic/test_duckdb_only_proof_state.py",),
        acceptance=("Mutable proof, constraint, formula and IPFS-pin operations work with every legacy cache/index file absent", "Compatibility shims import the unified repository and static guards reject direct JSON persistence", "Profile, declaration, solver, premise, policy, trust and revocation dimensions retain parity", "Only policy-approved proof summaries enter the publication plane"),
        track="proof",
        priority="P0",
    ),
    _task(
        "DQK-068", "DQK-G600", "Integrate AST and code-evidence producers in shadow mode",
        "Make repository extraction, software-contract caches, and code-evidence consumers write normalized AST blobs, symbols, imports, calls, effects, diagnostics, and evidence edges through the authority port.",
        depends_on=("DQK-031", "DQK-032", "DQK-033", "DQK-034", "DQK-046"),
        outputs=("ipfs_datasets_py/logic/software_contracts/repository.py", "ipfs_datasets_py/logic/software_contracts/cache.py", "ipfs_datasets_py/logic/software_contracts/registry.py", "ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py", "tests/integration/logic/software_contracts/test_duckdb_ast_shadow.py"),
        validations=("python -m pytest -q tests/integration/logic/software_contracts/test_duckdb_ast_shadow.py",),
        acceptance=("JSON bundle and DB projections have differential parity", "Source/hash/span/CID identity is exact", "Python and TypeScript parse failures remain durable without blocking unrelated files"),
        track="ast",
    ),
    _task(
        "DQK-069", "DQK-G600", "Promote AST and evidence consumers to DuckDB authority",
        "Run dual writes and make the DuckDB repository the default source for conflict, dependency, impact, validation-selection, and code-evidence consumers.",
        depends_on=("DQK-068",),
        outputs=("ipfs_datasets_py/logic/software_contracts/repository.py", "ipfs_datasets_py/logic/software_contracts/cache.py", "ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py", "tests/integration/logic/software_contracts/test_duckdb_ast_authority.py"),
        validations=("python -m pytest -q tests/integration/logic/software_contracts/test_duckdb_ast_authority.py",),
        acceptance=("Restart and source invalidation leave no stale symbol or edge", "Scheduling/impact decisions agree during parity soak", "JSON bundles are deterministic outbox exports"),
        track="ast",
    ),
    _task(
        "DQK-070", "DQK-G600", "Remove analysis-bundle file authority",
        "Stop polling/loading analysis_ast_index, objective, dependency, conflict, and code-evidence JSON as operational state; retain explicit compatibility exports only.",
        depends_on=("DQK-053", "DQK-058", "DQK-069"),
        outputs=("ipfs_datasets_py/logic/software_contracts/repository.py", "ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py", "tests/e2e/logic/software_contracts/test_duckdb_only_ast_evidence.py"),
        validations=("python -m pytest -q tests/e2e/logic/software_contracts/test_duckdb_only_ast_evidence.py",),
        acceptance=("AST/evidence consumers operate with legacy bundles absent", "Direct bundle writes occur only through named export commands", "Publication views apply repository and tenant filtering"),
        track="ast",
        priority="P0",
    ),
    _task(
        "DQK-071", "DQK-G700", "Integrate processor wallet ledger and checkpoint producers in shadow mode",
        "Inject the DuckDB ledger/checkpoint store into multi-chain storage, checkpoints, pipeline, API, and registry paths so blocks, transactions, transfers, UTXOs, events, cursors, finality, and reorgs shadow at ingestion time.",
        depends_on=("DQK-035", "DQK-036", "DQK-037", "DQK-038", "DQK-039", "DQK-046"),
        outputs=("ipfs_datasets_py/processors/wallets/storage.py", "ipfs_datasets_py/processors/wallets/checkpoints.py", "ipfs_datasets_py/processors/wallets/pipeline.py", "ipfs_datasets_py/processors/wallets/api.py", "ipfs_datasets_py/processors/wallets/registry.py", "tests/integration/processors/wallets/test_duckdb_shadow_ledger.py"),
        validations=("python -m pytest -q tests/integration/processors/wallets/test_duckdb_shadow_ledger.py",),
        acceptance=("All chain fixtures match JSONL and DB projections", "Checkpoint/reorg/deterministic-ID parity passes", "Secrets, signing payloads and unrestricted raw bytes never enter DuckDB"),
        track="wallet",
    ),
    _task(
        "DQK-072", "DQK-G700", "Promote processor wallet ledger state to DuckDB authority",
        "Run dual mode and make DuckDB authoritative for normalized ledger state and checkpoints; JSONL, Parquet, Arrow and CAR become outbox-driven exports.",
        depends_on=("DQK-071",),
        outputs=("ipfs_datasets_py/processors/wallets/storage.py", "ipfs_datasets_py/processors/wallets/checkpoints.py", "ipfs_datasets_py/processors/wallets/pipeline.py", "ipfs_datasets_py/processors/wallets/export.py", "tests/integration/processors/wallets/test_duckdb_authority_cutover.py"),
        validations=("python -m pytest -q tests/integration/processors/wallets/test_duckdb_authority_cutover.py",),
        acceptance=("Kill/restart at page, block, reorg and export boundaries loses or duplicates no record", "Stale cursor CAS fails", "Typed Parquet supports predicate pushdown without opaque-only payload authority"),
        track="wallet",
    ),
    _task(
        "DQK-073", "DQK-G700", "Remove processor wallet records and checkpoint file authority",
        "Remove implicit records.jsonl, .meta.json, JSON manifest, and in-memory checkpoint authority, keeping explicit imports/exports and encrypted/CID raw-object references.",
        depends_on=("DQK-053", "DQK-058", "DQK-072"),
        outputs=("ipfs_datasets_py/processors/wallets/storage.py", "ipfs_datasets_py/processors/wallets/checkpoints.py", "ipfs_datasets_py/processors/wallets/export.py", "tests/e2e/processors/wallets/test_duckdb_only_wallet_ledger.py"),
        validations=("python -m pytest -q tests/e2e/processors/wallets/test_duckdb_only_wallet_ledger.py",),
        acceptance=("Ingestion resumes from DuckDB with legacy files absent", "No raw secret-bearing data reaches the publication database", "Quack exposes redacted public ledger analytics only"),
        track="wallet",
        priority="P0",
    ),
    _task(
        "DQK-074", "DQK-G700", "Integrate legacy data-wallet producers in shadow mode",
        "Introduce a DuckDB repository/event port used by wallet repository, service, API, CLI, analytics, audit, and manifest mutations while encrypted blobs remain outside DuckDB and Quack.",
        depends_on=("DQK-035", "DQK-046"),
        outputs=("ipfs_datasets_py/wallet/repository.py", "ipfs_datasets_py/wallet/service.py", "ipfs_datasets_py/wallet/api.py", "ipfs_datasets_py/wallet/cli.py", "ipfs_datasets_py/wallet/duckdb_repository.py", "tests/integration/wallet/test_duckdb_shadow_repository.py"),
        validations=("python -m pytest -q tests/integration/wallet/test_duckdb_shadow_repository.py",),
        acceptance=("Every service mutation has an idempotent operation ID and parity receipt", "wallet JSON and analytics-ledger round-trip exactly", "Plaintext, keys, wraps and encrypted bytes are excluded from query publications"),
        track="wallet",
    ),
    _task(
        "DQK-075", "DQK-G700", "Promote legacy data-wallet metadata to DuckDB authority",
        "Run dual mode and make DuckDB authoritative for mutable wallet manifests, analytics, audit chain, grants, approvals, and public metadata while encrypted content stays in its content-addressed blob backend.",
        depends_on=("DQK-074",),
        outputs=("ipfs_datasets_py/wallet/repository.py", "ipfs_datasets_py/wallet/service.py", "ipfs_datasets_py/wallet/api.py", "ipfs_datasets_py/wallet/cli.py", "tests/integration/wallet/test_duckdb_authority_cutover.py"),
        validations=("python -m pytest -q tests/integration/wallet/test_duckdb_authority_cutover.py",),
        acceptance=("Concurrent API/CLI mutation, audit verification, grant lifecycle, restart and blob outage tests pass", "Snapshot and analytics hashes remain stable", "Stale service instances cannot overwrite a newer revision"),
        track="wallet",
    ),
    _task(
        "DQK-076", "DQK-G700", "Remove legacy data-wallet JSON repository authority",
        "Replace direct reads/writes and glob discovery of wallet-*.json and analytics-ledger.json with DuckDB repository calls; LocalWalletRepository remains explicit import/export compatibility only.",
        depends_on=("DQK-053", "DQK-058", "DQK-075"),
        outputs=("ipfs_datasets_py/wallet/repository.py", "ipfs_datasets_py/wallet/service.py", "ipfs_datasets_py/wallet/api.py", "ipfs_datasets_py/wallet/cli.py", "tests/e2e/wallet/test_duckdb_only_wallet_repository.py"),
        validations=("python -m pytest -q tests/e2e/wallet/test_duckdb_only_wallet_repository.py",),
        acceptance=("Service/API/CLI work with wallet JSON files absent", "A filesystem guard catches implicit snapshot or analytics-ledger writes", "Only separately approved aggregate analytics reach Quack"),
        track="wallet",
        priority="P0",
    ),
    _task(
        "DQK-077", "DQK-G1000", "Integrate audit, metric, alert, and structured-log producers in shadow mode",
        "Route existing audit, security, GraphRAG, observability, MCP, alert, and provenance event producers through the typed observability repository while their legacy file sinks remain an explicitly selected shadow authority.",
        depends_on=("DQK-046", "DQK-052"),
        outputs=("ipfs_datasets_py/duckdb_control/observability_adapters.py", "ipfs_datasets_py/audit/audit_logger.py", "ipfs_datasets_py/logic/security/audit_log.py", "ipfs_datasets_py/logic/observability/structured_logging.py", "ipfs_datasets_py/optimizers/graphrag/audit_logger.py", "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py", "ipfs_datasets_py/optimizers/common/logging_audit.py", "ipfs_datasets_py/alerts/alert_manager.py", "ipfs_datasets_py/mcp_server/logger.py", "tests/integration/test_duckdb_observability_shadow.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_observability_shadow.py",),
        acceptance=("Every mutable log/audit/alert record has a typed schema, stable event ID, classification, source revision and parity receipt", "Retries and restarts do not duplicate events", "Secrets and unrestricted SQL are redacted before persistence or publication", "Immutable evidence blobs remain content-addressed outside DuckDB"),
        track="security",
    ),
    _task(
        "DQK-078", "DQK-G1000", "Promote typed observability state to DuckDB authority",
        "Run fenced dual writes and promote lifecycle, audit, metric, alert, trace, query-profile, blocker, and provenance-event state to DuckDB, leaving standard stderr/console output as a disposable operational projection.",
        depends_on=("DQK-077",),
        outputs=("ipfs_datasets_py/duckdb_control/observability_cutover.py", "ipfs_datasets_py/audit/audit_logger.py", "ipfs_datasets_py/logic/security/audit_log.py", "ipfs_datasets_py/logic/observability/structured_logging.py", "ipfs_datasets_py/optimizers/graphrag/audit_logger.py", "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py", "ipfs_datasets_py/optimizers/common/logging_audit.py", "ipfs_datasets_py/alerts/alert_manager.py", "ipfs_datasets_py/mcp_server/logger.py", "tests/integration/test_duckdb_observability_cutover.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_observability_cutover.py",),
        acceptance=("One identified snapshot answers cross-domain audit and progress queries without scanning JSONL", "Retention and compaction preserve hash-chain and acceptance evidence", "Backpressure cannot starve supervisor heartbeats", "Rollback to shadow mode is fenced and receipted"),
        track="security",
    ),
    _task(
        "DQK-079", "DQK-G1000", "Remove mutable file authority from audit and observability producers",
        "Disable implicit JSON, JSONL, ad-hoc file-handler, metric-snapshot, and alert-state authorities after canary acceptance; retain only explicit deterministic exports and ephemeral human-readable console logs.",
        depends_on=("DQK-053", "DQK-058", "DQK-078"),
        outputs=("ipfs_datasets_py/audit/audit_logger.py", "ipfs_datasets_py/logic/security/audit_log.py", "ipfs_datasets_py/logic/observability/structured_logging.py", "ipfs_datasets_py/optimizers/graphrag/audit_logger.py", "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py", "ipfs_datasets_py/optimizers/common/logging_audit.py", "ipfs_datasets_py/alerts/alert_manager.py", "ipfs_datasets_py/mcp_server/logger.py", "scripts/validation/validate_duckdb_observability_cutover.py", "tests/e2e/test_duckdb_only_observability.py"),
        validations=("python -m pytest -q tests/e2e/test_duckdb_only_observability.py",),
        acceptance=("Runtime succeeds with legacy audit/log/metric JSON files absent", "Static and dynamic writer guards reject undeclared mutable file sinks", "Console logs cannot satisfy progress or completion authority", "Sanitized publication views exclude secrets and high-cardinality private payloads"),
        track="security",
        priority="P0",
    ),
    _task(
        "DQK-080", "DQK-G1100", "Refine inventory findings into reviewed database-native tasks before promotion",
        "Compare the initial producer inventory with the declared task/effect graph and implement the DQP-039 plan-revision adapter that emits bounded, deduplicated, exact-tree gap proposals plus a cryptographically verified approval-receipt command.",
        depends_on=("DQK-001", "DQK-003", "DQK-004", "DQK-056"),
        outputs=("ipfs_datasets_py/duckdb_control/inventory_refinement.py", "tests/integration/test_duckdb_inventory_refinement.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_inventory_refinement.py",),
        acceptance=("The adapter uses DQP's canonical plan-revision API rather than raw status mutation", "Proposals bind the exact repository tree and inventory snapshot and remain non-active until DQK-083 rollover", "Budgets cap generated goals, tasks, depth, retries, and model calls", "No analyzer can self-approve or directly mutate another repository plan", "A verifier rejects unsigned, stale, mismatched, incomplete, or self-approved refinement receipts"),
        track="rollout",
        priority="P0",
    ),
    _task(
        "DQK-081", "DQK-G1100", "Approve the inventory refinement revision before authority transition",
        "Run the inventory-to-plan comparison against the admitted repository snapshot, review and authorize every gap task or evidence-backed waiver, then CAS this gate from blocked to completed with the signed refinement receipt.",
        depends_on=("DQK-080", "DQK-083", "DQK-103"),
        outputs=(),
        validations=("python -m ipfs_datasets_py.duckdb_control.inventory_refinement verify --check",),
        acceptance=("The receipt binds the inventory snapshot, base and accepted plan roots, exact repository tree, reviewer authorization and decision CID", "All discovered mutable producers and consumers are dependency-ordered task effects or explicit accepted waivers", "If the accepted revision changes the graph, its governed generation rollover completed and old writers are fenced", "Only the dedicated revision-CAS acknowledgement command can complete this gate"),
        track="rollout",
        priority="P0",
        completion="manual",
        schedulable=False,
        initial_status="blocked",
        blocked_reason="inventory_refinement_approval_pending",
        authority_effect=MANUAL_GATE_AUTHORITY_EFFECT_IDS[REFINEMENT_GATE_TASK_ID],
    ),
    _task(
        "DQK-084", "DQK-G1210", "Pin and probe the DuckLake v1.0 capability profile",
        "Add a fail-closed DuckLake capability contract that binds the DuckDB version, platform-specific ducklake and quack artifacts, required httpfs/cloud-adapter extension artifacts and digests, DuckLake specification/catalog version, supported maintenance functions, explicit LOAD order, and disabled automatic install, load, and migration behavior to the DQK-082 environment receipt.",
        depends_on=("DQK-002", "DQK-082", "DQK-103"),
        outputs=("ipfs_datasets_py/ducklake/__init__.py", "ipfs_datasets_py/ducklake/capabilities.py", "tests/unit/ducklake/test_capabilities.py"),
        validations=("python -m pytest -q tests/unit/ducklake/test_capabilities.py",),
        acceptance=("DuckLake v1.0, Quack, and every enabled catalog-owner extension digest are attested", "ducklake, quack, and the selected object-store adapter are explicitly loaded before the configuration lock", "A DuckDB/platform/catalog mismatch fails before ATTACH", "Automatic extension installation/loading and automatic catalog migration remain off", "DuckLake can be disabled without affecting the authoritative control plane"),
        track="ducklake-foundation",
        priority="P0",
    ),
    _task(
        "DQK-085", "DQK-G1210", "Implement DuckDB + Quack catalog-shard, storage, and secret profiles",
        "Implement typed DuckDB + Quack catalog-shard profiles. Bind each logical catalog to one DuckDB metadata file on local or attached block storage, one canonical Quack endpoint, one active owner lease/process birth/fencing epoch, and one lifecycle-managed Parquet namespace in local or versioned object storage while source IPLD/IPFS CIDs remain provenance and secrets remain external references. Reject NFS, SMB, object URLs, and shared filesystem mounts for live catalog or companion-registry database files. Because a DuckDB-backed DuckLake catalog permits one client, distributed workers must submit typed remote requests to the single owner and must never open, copy into place, or network-mount the live catalog file. Scale by assigning datasets to independent catalog shards; active/passive recovery may transfer ownership only after the old owner stopped admission, its endpoint/token was revoked, object capabilities expired, all handles closed, and the successor verifies the catalog generation and acquires DuckDB's native file lock. DuckLake has no role or authorization layer, so a trusted broker independently authorizes every privileged operation and injects a one-use Quack capability only into an identity-bound trusted worker; untrusted agents never receive it. Provision separate object-delete IAM, least-privilege OS/network/storage identities, and encryption defaults before first ingest.",
        depends_on=("DQK-003", "DQK-004", "DQK-005", "DQK-084"),
        outputs=("ipfs_datasets_py/ducklake/config.py", "ipfs_datasets_py/ducklake/catalog.py", "tests/unit/ducklake/test_catalog_profiles.py"),
        validations=("python -m pytest -q tests/unit/ducklake/test_catalog_profiles.py",),
        acceptance=("Every distributed catalog shard uses one DuckDB metadata file opened by exactly one identity-bound DuckDB + Quack owner process", "Remote clients cannot directly open, mount, or mutate the catalog file; same-shard requests are serialized through the fenced owner while independent shards may run concurrently", "Live catalog and companion-registry files use local or attached block storage; NFS, SMB, object URLs, and shared filesystem authority paths fail closed", "Active/passive takeover requires a durable owner-generation receipt, proof the prior process stopped admission and is dead/fenced, endpoint/token revocation, expired storage capabilities, closed handles, the exact catalog digest/generation, and successful native DuckDB file-lock acquisition before open", "Catalog and Parquet data paths are normalized, allowlisted, repository-independent, and lifecycle-managed by DuckLake", "DuckLake supplies no role or authorization layer; the trusted broker independently authorizes every privileged call and injects a one-use Quack capability only into an identity-bound trusted worker", "Reader, writer, maintainer, and owner-broker identities have least-privilege endpoint/OS/object capabilities, while object deletion requires a separate short-lived IAM capability unavailable to ordinary readers and writers", "Passwords, tokens, signing material, and encryption keys never enter configuration projections or reach untrusted agents", "Tests prove every non-bootstrap or non-migration ATTACH sets CREATE_IF_NOT_EXISTS=false, OVERRIDE_DATA_PATH=false, and AUTOMATIC_MIGRATION=false; only a separately authorized bootstrap or migration operation can use other values"),
        track="ducklake-foundation",
        priority="P0",
    ),
    _task(
        "DQK-086", "DQK-G1210", "Define the lake registry, identities, and schema migrations",
        "Create checksummed application migrations and typed repositories at two scopes without modifying DuckLake's internal v1.0 tables. The existing small authoritative control DuckDB is the sole writer for catalog-shard identities, dataset-to-home-shard routing, owner-generation leases, canonical snapshot-vector roots, shard-migration receipts, promotion/release decisions, and signed shard projections. Each shard has a separate private companion owner-control DuckDB for only shard-local sources, schemas, file identities, ingest receipts, reader leases, logical-key reservations, outbox entries, ownership state, maintenance authorizations, retention, and publication lineage. A shard's companion registry runs in a private DuckDB DatabaseInstance that is never ATTACHed to or otherwise visible from the Quack-serving DatabaseInstance; owner-side code exchanges only typed content-bound records. A home-shard move drains the source and destination owners and completes one control-DB CAS receipt before either side resumes.",
        depends_on=("DQK-003", "DQK-004", "DQK-085"),
        outputs=("ipfs_datasets_py/ducklake/schema.py", "ipfs_datasets_py/ducklake/registry.py", "tests/unit/ducklake/test_registry.py"),
        validations=("python -m pytest -q tests/unit/ducklake/test_registry.py",),
        acceptance=("Logical dataset aliases are distinct from content and snapshot identities", "The small control DuckDB exclusively owns lake_catalog, dataset_home_shard, catalog_owner_generation, snapshot_vector_root, shard_migration, promotion_decision, promotion_execution, and lake_release_receipts authority", "Per-shard companions own reader_lease, logical_key_reservation, ingest_outbox, maintenance_authorization, and other shard-local state but cannot redefine the global shard ring, home assignment, owner generation, or vector root", "Every logical uniqueness/reference scope resolves to exactly one authoritative home shard; unsupported cross-shard uniqueness fails before ingest", "A home-shard move requires drained source/destination owners and one fenced control-DB CAS receipt before either resumes", "Each companion registry uses a separate private DuckDB DatabaseInstance and is never attached to or visible from the Quack-serving DatabaseInstance", "Signed shard projections are content-bound caches only and stale projections fail owner startup", "Migrations are ordered, checksummed, replayable, and owner gated", "Registry CAS, idempotency, ownership fencing, and provenance survive restart", "No mutable JSON or Parquet manifest is authoritative"),
        track="ducklake-foundation",
        priority="P0",
    ),
    _task(
        "DQK-087", "DQK-G1210", "Inventory and admit existing Parquet datasets safely",
        "Build a streaming Parquet discovery and admission service that captures canonical URI, streaming whole-file digest/CID, immutable object generation/version/ETag, footer and schema identity, row/file statistics, partition hints, producer and tenant provenance, policy classification, and an immutable decision receipt before any file reaches DuckLake; revalidate all identity evidence immediately before copy and registration.",
        depends_on=("DQK-001", "DQK-086"),
        outputs=("ipfs_datasets_py/ducklake/admission.py", "tests/integration/ducklake/test_parquet_admission.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_parquet_admission.py",),
        acceptance=("Discovery streams a whole-file digest plus bounded footer metadata without loading datasets", "Symlink, path traversal, replacement, object-generation/ETag drift, footer drift, duplicate, and schema-conflict cases fail closed", "The source identity is rechecked immediately before copy/register", "Sensitive sources require an explicit policy decision", "Admission records source ownership and whether a copy is required before registration"),
        track="ducklake-foundation",
    ),
    _task(
        "DQK-088", "DQK-G1210", "Implement transactional Parquet ingestion and ownership transfer",
        "Implement idempotent create/copy/register ingestion using lifecycle-managed, versioned owned lake namespaces, content-bound staging outside DATA_PATH, DuckLake transactions, registry reservations, outbox reconciliation, and `ducklake_add_data_files` only after an explicit lifecycle-ownership transfer authorization and receipt issued by the trusted owner broker rather than the ingest worker. Bind the authorization to the operation, caller identity and process birth, generation fence, exact catalog and DATA_PATH, source identity, owned destination object version and digest, lifecycle policy, allowed replace/delete semantics, nonce, and expiry, then revalidate it immediately before registration; never register an external or immutable CID source that DuckLake maintenance is not allowed to replace and delete.",
        depends_on=("DQK-044", "DQK-087", "DQK-094", "DQK-104"),
        outputs=("ipfs_datasets_py/ducklake/ingest.py", "tests/integration/ducklake/test_transactional_ingest.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_transactional_ingest.py",),
        acceptance=("Lost responses and retries create one logical snapshot", "Source files and source CIDs remain untouched; DuckLake receives a lifecycle-managed owned copy", "The ownership-transfer authorization is non-self-issued and binds the exact caller/process birth, generation fence, catalog, DATA_PATH, source identity, destination object version/digest, lifecycle policy, operation, nonce, and expiry", "Each privileged copy, registration, and ownership-transfer call is independently authorized and revalidated at use; one receipt cannot confer ambient future delete authority", "Staging files cannot be mistaken for orphans under DATA_PATH", "Partial object upload, catalog commit, or receipt publication is reconciled or quarantined", "Missing/extra columns and type promotion follow the validated DQK-094 schema policy rather than permissive defaults"),
        track="ducklake-foundation",
        priority="P0",
    ),
    _task(
        "DQK-089", "DQK-G1210", "Integrate Parquet producers through DuckLake shadow authority",
        "Route the dataset loader/saver/converter, knowledge-graph Parquet storage, and serialization entrypoints through the admitted lake port in shadow mode while preserving IPLD/CAR identities and retaining legacy outputs only as compared projections during the canary window. Producer selection must consume the current accepted DQK-081 inventory-refinement receipt and bind its exact inventory snapshot, repository tree, accepted plan root, and active materialized plan generation; seed declarations and stale inventories cannot authorize integration.",
        depends_on=("DQK-016", "DQK-046", "DQK-081", "DQK-088"),
        outputs=("ipfs_datasets_py/ducklake/adapters.py", "ipfs_datasets_py/core_operations/dataset_loader.py", "ipfs_datasets_py/core_operations/dataset_saver.py", "ipfs_datasets_py/core_operations/dataset_converter.py", "ipfs_datasets_py/knowledge_graphs/storage/parquet.py", "ipfs_datasets_py/processors/serialization/jsonl_to_parquet.py", "ipfs_datasets_py/processors/serialization/ipfs_parquet_to_car.py", "tests/integration/ducklake/test_parquet_producer_shadow.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_parquet_producer_shadow.py",),
        acceptance=("Every registered producer emits source, schema, snapshot, ownership, and parity receipts", "Existing Parquet/IPLD/CAR source byte identities do not drift", "Shadow integration consumes the current accepted DQK-081 inventory and exact active plan generation; stale inventory-snapshot, repository-tree, plan-root, or generation bindings fail closed", "A signed exact-tree inventory proves zero unowned public Parquet producers; waivers are reviewer-signed, path-scoped, justified, and expiring", "Shadow disagreement quarantines only the affected dataset"),
        track="ducklake-foundation",
    ),
    _task(
        "DQK-090", "DQK-G1220", "Implement reproducible explicit multi-shard snapshot vectors",
        "Capture and validate an immutable ordered vector with exactly one member per DuckDB + Quack DuckLake catalog shard: catalog identity, catalog-owner generation, Quack endpoint identity, catalog-global snapshot ID, schema version, storage root, included logical datasets, source revisions, and policy decision. Implement authoritative database-backed reader-lease acquire, renew, and release operations bound to the vector, worker process birth identity, task/run identity, lease token, deadline, and generation fence. The catalog owner—not a remote worker—must ATTACH its one DuckDB metadata file, set the member's SNAPSHOT_VERSION with CREATE_IF_NOT_EXISTS=false, OVERRIDE_DATA_PATH=false, and AUTOMATIC_MIGRATION=false, and return signed snapshot evidence through the typed Quack operation. Remote workers attach only the authenticated Quack endpoint, verify its owner generation and snapshot receipt before reading, renew while active, and release only their exact fenced lease; retry catalog races and never imply atomicity across independent shards.",
        depends_on=("DQK-085", "DQK-086", "DQK-104"),
        outputs=("ipfs_datasets_py/ducklake/snapshots.py", "tests/unit/ducklake/test_snapshot_vectors.py"),
        validations=("python -m pytest -q tests/unit/ducklake/test_snapshot_vectors.py",),
        acceptance=("Snapshot-vector identity is deterministic and order independent with one member per DuckDB + Quack catalog shard", "Every member binds the exact Quack endpoint, catalog-owner generation, DuckDB catalog identity, and catalog-global snapshot", "Every worker acquires an authoritative lease before reading, renews it while active, and releases only its exact token after all reads finish", "Lease acquire, renew, and release bind process birth identity plus task/run and generation fences; PID reuse, a stale fence, or a foreign token fails closed", "Only the fenced owner opens the catalog file and proves its DuckLake ATTACH SNAPSHOT_VERSION equals the receipted catalog-global snapshot; remote workers open only the authenticated Quack endpoint", "Every owner-side non-bootstrap or non-migration DuckLake ATTACH sets CREATE_IF_NOT_EXISTS=false, OVERRIDE_DATA_PATH=false, and AUTOMATIC_MIGRATION=false", "The database exposes the exact live reader-lease set consumed by DQK-096 maintenance; crashed readers lose protection only through bounded lease expiry", "Stale, expired, mixed-tenant, duplicate-catalog, owner-generation, or schema-incompatible members fail closed", "Time-travel replay returns the same logical result or a typed retention error", "No snapshot vector or reader lease is represented only by a file"),
        track="ducklake-query",
        priority="P0",
    ),
    _task(
        "DQK-091", "DQK-G1220", "Build logical federation over multiple Parquet datasets",
        "Map registered DuckDB + Quack DuckLake catalog shards, schemas, tables, and views into versioned logical datasets; compile bounded unions and joins with explicit field-ID/type reconciliation, partition and statistics pruning, tenant policy, and snapshot-vector binding across heterogeneous Parquet sources. Push each shard-local subplan through that shard's typed Quack endpoint and combine only snapshot-receipted results; never ATTACH a remote shard's catalog file.",
        depends_on=("DQK-088", "DQK-090", "DQK-094"),
        outputs=("ipfs_datasets_py/ducklake/federation.py", "tests/integration/ducklake/test_federated_parquet_query.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_federated_parquet_query.py",),
        acceptance=("Queries aggregate at least two independently versioned Parquet datasets served by distinct DuckDB + Quack catalog shards", "The federation plan binds each shard endpoint, owner generation, snapshot, schema, and subresult digest", "No federating worker opens, copies, or network-mounts a catalog metadata file", "Field-ID remapping, missing columns, lossless type promotion, and partition evolution are deterministic", "File and row pruning are visible in bounded query evidence", "One unavailable catalog yields a typed policy-selected partial or failed result"),
        track="ducklake-query",
    ),
    _task(
        "DQK-092", "DQK-G1220", "Execute DuckLake subqueries in parallel with backpressure",
        "Integrate lake subplans with the trusted parallel query broker so independent snapshot-bound DuckDB clients execute concurrently against distinct catalog-shard Quack endpoints under per-catalog connection, row, byte, memory, time, spill, and cancellation budgets while control-plane capacity remains reserved. Same-shard catalog mutations remain serialized by that shard's single owner. Each worker must acquire its DQK-090 authoritative reader lease before opening the remote Quack attachment, renew it throughout all scans and result materialization, and release it after its connections and file readers close; cancellation, worker death, PID reuse, owner failover, or a generation-fence change must not leave a renewable stale lease.",
        depends_on=("DQK-040", "DQK-041", "DQK-042", "DQK-091"),
        outputs=("ipfs_datasets_py/ducklake/execution.py", "ipfs_datasets_py/duckdb_control/parallel_query.py", "tests/integration/ducklake/test_parallel_execution.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_parallel_execution.py",),
        acceptance=("Independent shard scans overlap without sharing mutable connections while same-shard mutations are serialized", "Every worker acquires, renews, and releases an authoritative DQK-090 lease around the complete lifetime of its remote Quack attachment, scan, and result materialization", "Lease evidence binds process birth identity, endpoint owner generation, and task/run/generation fences, and cancellation closes readers before release while crash recovery relies on bounded expiry", "Deadlines and cancellation propagate to every worker", "A slow or failed catalog owner cannot starve supervisor heartbeats or unrelated shards", "Receipts bind plan, snapshot vector, Quack endpoint/owner identity, reader-lease identity, resource use, result digest, and partial-failure policy"),
        track="ducklake-query",
    ),
    _task(
        "DQK-104", "DQK-G1220", "Implement the distributed DuckDB + Quack DuckLake catalog manager",
        "Implement one dedicated internal DuckDB + Quack owner service per DuckLake catalog shard without starting or promoting a production endpoint in this code-completion task. Each identity-bound process acquires a durable catalog-owner generation lease before it exclusively opens that shard's local/block-storage DuckDB metadata file, acquires DuckDB's native file lock, explicitly loads the pinned DuckLake, Quack, and object-store extensions, and attaches exactly one DuckLake catalog. A separate owner-side coordinator uses the private DQK-086 companion-registry DatabaseInstance; that database is never ATTACHed to or visible from the Quack-serving DatabaseInstance. Distributed readers and writers connect only through Quack; no second process may directly open, copy into place, or network-mount the live catalog file. The trusted broker validates each signed structured operation outside the Quack SQL callback and injects a one-use endpoint credential only into an identity-bound trusted worker. It then emits a versioned allowlisted parameterized SQL transaction, serializes same-shard mutations, and exposes bounded catalog, namespace, schema, table, snapshot, ingest-registration, and maintenance-intent operations. Independent shards may execute concurrently and DQK-091 federates their receipted snapshot results. Because quack_authorization_function sees a connection identity and full SQL text rather than a signed structured request, install and attest a non-default globally visible callback as defense in depth that exact-allows only the already-authorized operation's canonical SQL/template identity and rejects everything else; prefix/regex filtering is forbidden. On lease loss the incumbent stops admission, revokes endpoint/token access, lets storage capabilities expire, closes every session and file handle, and exits. Active/passive failover may open only after that proof, exact catalog/registry generation verification, endpoint/token rotation, and native file-lock acquisition. Quack supplies distribution and transport, never task/lease/CAS authority, replication, or multi-owner storage semantics; untrusted agents never receive raw SQL, reusable Quack tokens, catalog-file access, arbitrary ATTACH, extension-loading, or object-store access. Production catalog mutation remains disabled until DQK-088 and DQK-094 have installed governed ingestion and distributed logical-key reservations and the independently signed DQK-102 promotion gate authorizes the exact cutover.",
        depends_on=("DQK-041", "DQK-049", "DQK-050", "DQK-084", "DQK-085", "DQK-086"),
        outputs=("ipfs_datasets_py/ducklake/quack_catalog.py", "ipfs_datasets_py/ducklake/catalog_service.py", "scripts/ops/ducklake_quack_catalog.py", "tests/integration/ducklake/test_quack_catalog_management.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_quack_catalog_management.py",),
        acceptance=("This implementation task creates no production catalog endpoint and performs no production DuckLake mutation; activation remains held behind DQK-088, DQK-094, and the signed DQK-102 gate", "DuckDB with the pinned DuckLake extension owns every catalog file and Quack provides the authenticated distributed transport", "Exactly one identity-bound owner process and generation lease exist per catalog shard; remote clients cannot directly open, copy, or mount its DuckDB metadata file", "The catalog file is local/block-storage only and the successor obtains DuckDB's native file lock after every predecessor handle closes", "Same-shard mutations are serialized and idempotent, while independent catalog shards can run concurrently and are federated only through explicit snapshot vectors", "The Quack-serving DatabaseInstance attaches only its selected DuckLake catalog; the separate private companion-registry DatabaseInstance is never remotely visible", "The Quack catalog-owner process has a distinct OS/network identity from the sanitized publication gateway and can reach only its selected DuckDB catalog file and owned storage namespace", "The reusable default server token is not a per-operation authority; a non-default quack_authentication_function or authenticating proxy atomically consumes a one-use capability on each fresh connection and binds its authenticated session ID to subsequent authorization", "The trusted broker retains reusable endpoint secrets, injects only a one-use capability into an identity-bound trusted worker, and returns typed results/receipts; untrusted agents receive neither", "A task-owned handler independently verifies the signed structured operation before SQL construction; quack_authorization_function is an exact full-SQL/connection defense-in-depth callback, not the primary authorization boundary", "The server attests a non-default globally visible quack_authorization_function before accepting a connection; the callback exact-allows only the broker's versioned canonical template and authenticated connection/operation identities, never a prefix or regex approximation, and a missing, reset, changed, or permissive hook fails closed", "Every operation is a signed, expiring, idempotent allowlisted template bound to caller process birth, tenant, catalog, starting snapshot, schema, expected effects, operation ID, owner generation fence, and resource budget", "Arbitrary SQL delivered by quack_query or an attached remote .query call, ATTACH/DETACH/INSTALL/LOAD/SECRET, multi-statement escape, DuckLake internal-table DML, cross-catalog access, unbounded results, and credential/token export fail closed", "Each catalog-scoped server proves exactly one selected catalog and rejects concurrent cross-catalog overlap; shutdown closes every connection and file handle before releasing the owner lease and invalidating its token", "Lease loss stops admission and revokes the endpoint before capability expiry and session/file-handle teardown; stale incumbents cannot keep serving", "Active/passive takeover proves the prior owner/session is dead and fenced, verifies exact catalog and registry generations, rotates endpoint identity/token, acquires the native file lock, and never overlaps two owners", "Mutation receipts bind the exact authentication session, signed-request verification, authorization callback blob/config, Quack and DuckDB profiles, request, catalog/network policy, before/after snapshot, affected logical objects, outbox/idempotency state, and audit event", "A lost reply or Quack/DuckDB owner restart replays from the durable operation ID without duplicating a catalog mutation", "The gateway binds localhost/private-network or TLS-proxy policy and scrubs tokens, credentials, secrets, and raw SQL from DuckDB/Quack logs", "The gateway cannot read control, proof, graph-writer, AST-writer, wallet, secret, or sanitized-publication authority catalogs"),
        track="ducklake-query",
        priority="P0",
    ),
    _task(
        "DQK-093", "DQK-G1220", "Expose allowlisted DuckLake query and export APIs",
        "Add CLI, Python, and MCP operations for catalog/dataset discovery, snapshot selection, explain, bounded aggregate query, cancellation, and deterministic export through the existing template registry and the DQK-104 DuckDB + Quack catalog-management gateway; callers never receive catalog credentials, Quack tokens, arbitrary ATTACH, or unrestricted SQL.",
        depends_on=("DQK-043", "DQK-092", "DQK-104"),
        outputs=("ipfs_datasets_py/ducklake/api.py", "ipfs_datasets_py/ducklake/cli.py", "ipfs_datasets_py/mcp_server/tools/duckdb_query_tools.py", "tests/mcp/test_ducklake_query_tools.py"),
        validations=("python -m pytest -q tests/mcp/test_ducklake_query_tools.py",),
        acceptance=("Every operation is an allowlisted parameterized template", "Catalog-management calls use DQK-104 while query/export calls use bounded snapshot-bound workers or the sanitized publication plane", "Pagination, cancellation, snapshot/time-travel selection, and export digests are bounded and reproducible", "Secrets, encryption keys, raw catalog strings, Quack tokens, and unrestricted object URIs are redacted", "Untrusted remote access remains a typed broker or sanitized publication operation rather than direct authority-catalog Quack access"),
        track="ducklake-query",
    ),
    _task(
        "DQK-094", "DQK-G1220", "Enforce schema evolution and application data constraints",
        "Implement versioned field-ID contracts, lossless type-promotion rules, default/missing/extra-column policy, tenant and domain checks, and reject evidence before DuckLake commits because the lake layer supplies no PK, UNIQUE, FK, CHECK, or index enforcement. Store every logical uniqueness/reference reservation and its durable outbox in the selected shard's private companion owner-control DuckDB, separate from DuckLake's internal metadata tables and never visible to the Quack-serving DatabaseInstance. Resolve every uniqueness/reference scope through the DQK-086 authoritative dataset-home-shard routing before reservation; reject unsupported constraints spanning shards. The single fenced DuckDB + Quack catalog owner must reserve the exact logical key and idempotency key before the non-atomic DuckLake snapshot commit, serialize competing same-shard operations, then reconcile and terminalize the reservation with the exact snapshot through the durable outbox; never imply a cross-file transaction or use a read-before-write check. A successful claim is terminal and is never released, reassigned, or reused; crash recovery may reclaim only a proven incomplete or failed claim.",
        depends_on=("DQK-086", "DQK-087", "DQK-104"),
        outputs=("ipfs_datasets_py/ducklake/contracts.py", "tests/integration/ducklake/test_schema_evolution.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_schema_evolution.py",),
        acceptance=("Add/drop/rename and lossless promotion replay across historic snapshots", "Invalid domain, uniqueness, reference, and tenant records are rejected before commit", "The authoritative reservation and durable outbox live in the per-shard private companion owner-control DuckDB, separate from DuckLake internal metadata and never visible to the Quack-serving DatabaseInstance", "Every uniqueness/reference scope resolves to exactly one authoritative home shard; an unsupported cross-shard scope fails before object copy or snapshot mutation", "Every write reaches the single fenced catalog owner and acquires a persistent logical-key/idempotency-key reservation before the non-atomic snapshot boundary, then terminalizes it with the exact committed snapshot through the durable outbox", "Recovery reconciles reservation, object, catalog snapshot, and outbox states without claiming atomicity across files", "Concurrent same-key remote requests are serialized at the owner, contend on the durable reservation, and exactly one wins", "Independent catalog shards may progress concurrently without sharing a reservation database", "A successful reservation is never released or reused; crash recovery may reclaim only proven incomplete or failed claims", "Constraint evidence binds the exact source files and schema revision", "Schema changes require an authorized migration receipt and rollback plan"),
        track="ducklake-query",
        priority="P0",
    ),
    _task(
        "DQK-095", "DQK-G1220", "Prove distributed Quack concurrency and fenced catalog-owner recovery",
        "Build an owner-locked, idempotent, digest-pinned hermetic harness for multiple isolated DuckDB + Quack catalog-owner processes and an S3-compatible object store. Bind every process, container, endpoint, network, catalog file, companion registry, and volume to one exact run owner, reconcile repeated create and teardown calls, clean only owned resources after normal completion or process death, and never inspect, reuse, or delete foreign resources. Exercise concurrent remote writers against one catalog owner, parallel operations across independent shards, same-logical-key reservations, lost replies, duplicate idempotency keys, owner-process death, fenced active/passive restart, object-store latency, snapshot readers, and split-brain attempts while verifying logical-once ingest/publication outcomes. Inject the crash after a DuckLake snapshot commit but before companion-outbox completion; the supported DuckLake snapshot metadata or application marker must retain the operation ID so restart reaches one terminal receipt or quarantine. Never claim that two DuckDB processes may concurrently own one catalog file or that Quack supplies replication.",
        depends_on=("DQK-051", "DQK-088", "DQK-090", "DQK-094"),
        outputs=("requirements/ducklake-services.lock", "scripts/ops/ducklake_test_services.py", "ipfs_datasets_py/ducklake/concurrency.py", "tests/chaos/test_ducklake_multiwriter.py"),
        validations=("python -m pytest -q tests/chaos/test_ducklake_multiwriter.py",),
        acceptance=("DuckDB, Quack, DuckLake, and object-store artifacts/images are immutable-digest pinned and emit a capability receipt", "Process, endpoint, container, network, catalog-file, registry, and volume create/reconcile/teardown are owner-locked and idempotent for one exact run identity", "Normal completion and injected process death clean only owned resources and leave no process, endpoint, container, network, or volume leaks", "The validation suite fails rather than skips when the owned harness is unavailable", "One DuckDB + Quack owner is the sole client of each catalog file; a second live owner or direct file opener is rejected by generation policy and the native DuckDB file lock", "Two remote writers racing the same logical key through one owner prove one durable reservation winner", "Independent catalog shards execute concurrently and one slow shard does not serialize the others", "A crash after the DuckLake commit may create a temporary in-doubt snapshot; its persisted operation ID is detected on restart and bounded reconciliation yields exactly one terminal receipt or quarantine", "No snapshot remains terminally unreceipted and recovery never creates a second logical transition for the same operation ID", "An owner-process outage and cold active/passive restart drill proves bounded admission stop, session teardown, endpoint/token revocation, storage-capability expiry, native-lock handoff, fencing, and recovery without claiming Quack replication or built-in high availability", "Lease loss in an already-running incumbent stops new requests and tears down sessions before a successor can open; stale startup and split-brain cases are tested separately", "A split-brain or stale-generation owner is rejected before opening the catalog file", "Catalog recovery cannot point metadata at missing or foreign Parquet files", "Long readers and writers remain observable and cannot block control leases"),
        track="ducklake-query",
        priority="P0",
    ),
    _task(
        "DQK-096", "DQK-G1230", "Govern partitioning, compaction, retention, and cleanup",
        "Implement receipted maintenance policy for partition/sort evolution, file and row-group sizing, inlined-data flush, adjacent-file merge, delete-file rewrite, statistics, catalog-global snapshot expiration, scheduled-file cleanup, and orphan reconciliation with dry-run as the default destructive mode. Every compaction, expiration, scheduled cleanup, and orphan action requires a non-self-issued operation authorization from the trusted owner broker and a mutation fence; its accepted dry-run must bind the exact caller process birth and generation fence, catalog identity, starting snapshot/version, authoritative DQK-090 reader-lease set, policy, action, candidate file set, nonce, and expiry. Execution must independently reauthorize and revalidate those bindings, obtain a separate scoped object-delete IAM capability for any deletion, and receipt the exact resulting snapshot and created/deleted file set. Partition catalogs by retention class; bare CHECKPOINT and unattended cleanup_all are forbidden.",
        depends_on=("DQK-047", "DQK-088", "DQK-090", "DQK-094", "DQK-095", "DQK-104"),
        outputs=("ipfs_datasets_py/ducklake/maintenance.py", "tests/integration/ducklake/test_maintenance.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_maintenance.py",),
        acceptance=("Partition changes affect new files without invalidating old snapshots", "Each catalog has one strict global retention class and snapshot expiry precedes cleanup", "Every compaction, expiration, scheduled cleanup, and orphan action is independently authorized by a trusted owner-broker identity distinct from the maintainer and fence-checked before the single catalog owner mutates it; possession of a Quack token cannot self-authorize maintenance", "Dry-run and execution receipts bind the exact caller/process birth and catalog-owner generation fence, exact catalog identity, starting snapshot/version, authoritative reader-lease set from DQK-090, policy, action and authorization, candidate file set, nonce/expiry, resulting snapshot, and created/deleted file set", "Destructive execution must exactly match a current accepted dry-run, independently reauthorize at use, and obtain separate scoped object-delete IAM or fail closed", "Maintenance consumes authoritative DQK-090 acquire/renew/release state, not inferred timestamps, to protect the maximum active-reader window", "Bare CHECKPOINT and automated cleanup_all are rejected", "Staging is outside DATA_PATH and live upload leases prevent orphan deletion", "Orphan deletion requires owned-namespace proof, age threshold, dry-run evidence, non-self-issued authorization, and the same catalog/snapshot/lease/file-set fence", "Compaction creates new file identities while preserving logical rows, schema, provenance, and retained old-snapshot files"),
        track="ducklake-operations",
        priority="P0",
    ),
    _task(
        "DQK-097", "DQK-G1230", "Enforce lake catalog, storage, encryption, and publication security",
        "Enforce the DQK-085 owner-broker boundary: DuckLake has no role or authorization layer and a Quack token is only a transport capability, never sufficient operation authorization. A trusted owner broker independently authorizes each privileged call and issues short-lived, operation-scoped Quack/object capabilities; ordinary readers and writers cannot open catalog files or obtain the separate object-delete IAM capability. Apply tenant/schema prefixes, encrypted Parquet policy, endpoint and owner-generation audit, and a fenced sanitizer that copy-publishes approved snapshot-bound aggregates into the separate Quack publication DuckDB without attaching the authority lake catalog.",
        depends_on=("DQK-049", "DQK-058", "DQK-085", "DQK-093", "DQK-104"),
        outputs=("ipfs_datasets_py/ducklake/security.py", "ipfs_datasets_py/ducklake/publication.py", "tests/security/test_ducklake_boundaries.py"),
        validations=("python -m pytest -q tests/security/test_ducklake_boundaries.py",),
        acceptance=("Tests prove DuckLake exposes no native role layer and a Quack token alone cannot authorize any privileged lake call", "The trusted owner broker and credential issuer are distinct from workers, independently authorize every privileged call, and bind short-lived capabilities to the exact operation, caller/process birth, endpoint owner generation, resource, nonce, and expiry", "Readers, writers, maintainers, and catalog owners have distinct endpoint/OS/storage capabilities, and only an independently authorized deletion receives separate scoped object-delete IAM", "No remote worker identity can directly open, copy, replace, or mount an authority catalog file or companion registry", "DuckLake encryption keys and all credentials are absent from logs, exports, receipts, and agent-visible Quack responses", "The sanitized publication Quack OS/network identity cannot reach authority catalog files, companion registries, object storage, or secret endpoints and cannot INSTALL/LOAD ducklake, quack, or httpfs", "The sanitized publication Quack process cannot open or ATTACH the DuckLake authority catalog; only the distinct broker-owned DQK-104 catalog owner has a narrowly scoped attachment", "Publication rows bind sanitizer policy, source snapshot vector, schema, and digest"),
        track="ducklake-operations",
        priority="P0",
    ),
    _task(
        "DQK-098", "DQK-G1230", "Back up and restore catalog metadata plus Parquet storage",
        "Implement a coordinated cold recovery manifest and drill for each DuckDB + Quack catalog shard. Drain and fence remote writers, readers, and maintenance; stop admission; close the sole catalog owner; and prove all DuckDB catalog and companion-registry file handles are closed. An isolated backup process then opens the raw DuckDB metadata and companion databases read-only and uses DuckDB COPY FROM DATABASE and/or an immutable byte snapshot to create digested backup databases, together with a versioned object-store generation/replica/CID inventory and encryption policy. Never run DuckLake CHECKPOINT during capture because it can flush, expire, rewrite, and delete lake data. Prohibit owner failover, compaction, expiration, scheduled cleanup, and orphan deletion throughout capture, revalidate catalog-to-object reachability plus unchanged owner fences before completion, and never copy a live catalog file behind the owner's back. Restore into an isolated new owner generation and endpoint, verify file integrity, time travel and snapshot vectors, then promote only through a fenced cold active/passive decision receipt with declared RPO/RTO. DuckDB + Quack supplies no PITR, replication, or built-in high availability.",
        depends_on=("DQK-047", "DQK-096", "DQK-097"),
        outputs=("ipfs_datasets_py/ducklake/recovery.py", "tests/integration/ducklake/test_backup_restore.py"),
        validations=("python -m pytest -q tests/integration/ducklake/test_backup_restore.py",),
        acceptance=("Catalog-only, companion-registry-only, or object-only backups cannot be marked complete", "Capture proves an exact writer/reader/maintenance drain, one fenced owner generation, closed catalog/registry file handles, and immutable DuckDB file digests before copying", "An isolated process opens the closed raw metadata and companion databases read-only and emits content-digested COPY FROM DATABASE or byte-snapshot outputs", "DuckLake CHECKPOINT is forbidden throughout backup capture", "No backup path reads or copies the live catalog file while a Quack owner can mutate it", "Every recovery manifest binds an immutable versioned object inventory rather than a mutable bucket listing", "Owner failover, compaction, snapshot expiration, scheduled cleanup, and orphan deletion are prohibited for the full capture window", "Completion revalidates owner and workload fences, catalog/registry digests, object inventory versions, and reachability of every catalog-referenced file", "Restore detects missing, replaced, orphaned, and undecryptable files", "Historic snapshots replay within the declared retention window", "Restored service starts under a new owner generation and endpoint identity without overlap", "The drill declares and measures cold-failover RPO/RTO and never claims PITR, replication, or built-in high availability", "Promotion binds exact catalog, registry, storage, schema, extension, policy, and verification identities"),
        track="ducklake-operations",
        priority="P0",
    ),
    _task(
        "DQK-099", "DQK-G1230", "Run the DuckLake shadow and distributed canary",
        "Canary representative knowledge-graph, vector, proof-evidence, AST, wallet-public, legal, and general dataset Parquet sources through admission, ingestion, multi-catalog aggregation, concurrency, time travel, maintenance, backup/restore, sanitized publication, and rollback while legacy producers remain shadow projections.",
        depends_on=("DQK-048", "DQK-060", "DQK-063", "DQK-066", "DQK-069", "DQK-072", "DQK-075", "DQK-089", "DQK-093", "DQK-095", "DQK-098", "DQK-100"),
        outputs=("scripts/ops/ducklake_canary.py", "tests/e2e/test_ducklake_canary.py"),
        validations=("python -m pytest -q tests/e2e/test_ducklake_canary.py",),
        acceptance=("Every representative domain passes schema, row, identity, snapshot, performance, security, and restore parity using the final domain-producer lineage consumed by DQK-053", "The canary inspects every non-bootstrap or non-migration ATTACH and proves CREATE_IF_NOT_EXISTS=false, OVERRIDE_DATA_PATH=false, and AUTOMATIC_MIGRATION=false", "Concurrent writes and analytical scans preserve control heartbeat SLOs", "Failure rolls back or quarantines one dataset without deleting source files", "The canary proves the Quack beta feature gate and local fallback, and emits the exact DQK-050 compatibility/risk receipt", "The canary emits a database-native DuckLakeCanaryReceipt@1"),
        track="ducklake-operations",
        priority="P0",
    ),
    _task(
        "DQK-100", "DQK-G1230", "Implement DuckLake authority promotion and legacy-manifest cutover controls",
        "Implement, without executing production promotion, the fenced command, verifier, dry run, rollback, and receipt schema that can make the admitted lake registry and snapshot receipts authoritative for integrated Parquet producers and disable mutable sidecar manifests and implicit directory scans. The command must require a fresh exact-HEAD producer inventory or a signed baseline plus complete content-addressed delta, an unexpired independently signed DQK-102 promotion decision, exact process-birth and generation fences, and current canary/recovery/security evidence at the point of use; implementation-task completion grants no authority and changes no runtime authority.",
        depends_on=("DQK-089", "DQK-097"),
        outputs=("ipfs_datasets_py/ducklake/cutover.py", "ipfs_datasets_py/core_operations/dataset_loader.py", "ipfs_datasets_py/core_operations/dataset_saver.py", "ipfs_datasets_py/core_operations/dataset_converter.py", "ipfs_datasets_py/knowledge_graphs/storage/parquet.py", "ipfs_datasets_py/processors/serialization/jsonl_to_parquet.py", "ipfs_datasets_py/processors/serialization/ipfs_parquet_to_car.py", "tests/e2e/test_ducklake_authority_cutover.py"),
        validations=("python -m pytest -q tests/e2e/test_ducklake_authority_cutover.py",),
        acceptance=("Completing DQK-100 does not alter production authority or disable a legacy producer", "The implementation rejects promotion without an unexpired independently signed DQK-102 decision bound to the exact actor/process birth, generation, repository tree, evidence set, and requested transition", "Cutover requires either a fresh exact-HEAD producer scan or a signed baseline plus a complete content-addressed delta through HEAD", "A stale baseline, incomplete delta, or new, changed, or unowned producer gap cannot authorize promotion", "Inventory gaps route to governed DQK-081 plan revision and DQK-083 generation rollover rather than retrying against a stale generation", "Every waiver in the resulting exact-tree inventory is current, reviewer-signed, path-scoped, justified, and expiring", "Synthetic-decision tests prove unregistered directory contents cannot silently enter a query and immutable source Parquet data remains content addressed", "A successful invocation emits a generation-fenced execution receipt binding before/after authorities and a bounded receipted rollback"),
        track="ducklake-operations",
        priority="P0",
    ),
    _task(
        "DQK-102", "DQK-G1230", "Authorize and execute DuckLake authority promotion",
        "After the shared DQK-053 canary gate, have an independent authorized reviewer sign the exact promotion decision, then invoke the DQK-100 fenced command once to promote the admitted lake registry and snapshot receipts as discovery/query authority and disable legacy mutable Parquet manifest and directory-scan authority. Revalidate the exact repository HEAD inventory, accepted plan generation, canary/recovery/security evidence, actor process birth, and authority fence immediately before mutation, persist both the signed decision and execution receipt in the authoritative database, and CAS-complete this manual gate only after post-transition verification succeeds.",
        depends_on=("DQK-053", "DQK-100"),
        outputs=(),
        validations=("python -m ipfs_datasets_py.ducklake.cutover verify-promotion --check",),
        acceptance=("The promotion decision is signed by an authorized identity independent of the DQK-100 implementer and runtime actor and binds the exact transition, repository tree, plan generation, evidence set, expiry, and rollback window", "The independent reviewer explicitly accepts Quack's current beta/not-production-ready risk, binds the exact DQK-050 compatibility receipt, keeps the feature gate and local fallback live, and defines the DuckDB 2.0 requalification trigger", "Immediately before execution a fresh exact-HEAD scan or signed baseline plus complete content-addressed delta proves zero unowned producer gaps and every waiver is current, reviewer-signed, path-scoped, justified, and expiring", "A stale or incomplete inventory, evidence set, signature, process-birth identity, or generation fence blocks without changing authority and routes gaps through DQK-081 plus DQK-083", "The execution receipt binds the decision, actor/process birth, before/after authority identities, catalog and snapshot vectors, changed producers, rollback fence, and post-transition verification", "Public producers and consumers operate with legacy mutable Parquet manifests and implicit directory-scan authority absent", "Only the dedicated signed promotion acknowledgement can complete this gate"),
        track="ducklake-operations",
        priority="P0",
        completion="manual",
        schedulable=False,
        initial_status="blocked",
        blocked_reason="ducklake_promotion_approval_pending",
        authority_effect=MANUAL_GATE_AUTHORITY_EFFECT_IDS[PROMOTION_GATE_TASK_ID],
    ),
    _task(
        "DQK-101", "DQK-G1230", "Verify and publish the DuckLake layer release receipt",
        "Validate the complete DuckLake goal graph against the exact repository tree, environment/extension profile, every DuckDB + Quack catalog-shard and owner generation, companion registry, storage root, schema checksum, representative snapshot vector, canary, maintenance, restore, security, publication, and the exact signed DQK-102 promotion decision/execution evidence, then store DuckLakeLayerReleaseReceipt@1 in the authoritative database.",
        depends_on=("DQK-050", "DQK-102"),
        outputs=("ipfs_datasets_py/ducklake/release.py", "tests/e2e/test_ducklake_release.py"),
        validations=("python -m pytest -q tests/e2e/test_ducklake_release.py",),
        acceptance=("The receipt is stored in the DQK-086 lake_release_receipts authority table rather than a Markdown/JSON file", "It binds every DuckDB + Quack catalog shard, catalog file and companion-registry digest, owner generation/endpoint identity, task completion/validation ID, storage identity, snapshot vector, policy, extension, Git tree, expiry, and the exact DQK-102 signed decision plus execution receipt", "It proves no catalog file had two owners and no remote client opened an authority catalog directly during the canary", "It binds the Quack beta risk acceptance, exact DQK-050 compatibility receipt, enabled fallback/feature gate, and DuckDB 2.0 requalification policy", "Missing, stale, mismatched, or self-approved DQK-102 promotion evidence fails closed", "Missing or stale canary, restore, maintenance, security, or cutover evidence fails closed", "A sanitized release projection can be exported without exposing credentials or encryption keys"),
        track="ducklake-operations",
        priority="P0",
    ),
    _task(
        "DQK-053", "DQK-G1100", "Run domain canaries and prove cutover/rollback gates",
        "Canary the supervisor, proof, graph/vector, AST, wallet, observability, and DuckLake namespaces in dependency order using shadow/dual authority, SLO/parity/security/restore evidence, and an explicit rollback window.",
        depends_on=("DQK-024", "DQK-030", "DQK-034", "DQK-039", "DQK-046", "DQK-047", "DQK-051", "DQK-052", "DQK-056", "DQK-058", "DQK-060", "DQK-063", "DQK-066", "DQK-069", "DQK-072", "DQK-075", "DQK-078", "DQK-081", "DQK-099"),
        outputs=("scripts/ops/duckdb_quack_canary.py", "tests/e2e/test_duckdb_quack_canary.py"),
        validations=("python -m pytest -q tests/e2e/test_duckdb_quack_canary.py",),
        acceptance=("Each authority promotion has evidence and a tested rollback", "Canary failures quarantine only their namespace", "Legacy producers become export-only after promotion"),
        track="rollout",
    ),
    _task(
        "DQK-054", "DQK-G1100", "Implement database-native residual analysis and self-improvement",
        "Run bounded datasets inventory, schema, parity, performance, blocker, and coverage analyzers against identified snapshots, then submit deduplicated findings through the DQP-039 database-native planning interface.",
        depends_on=("DQK-042", "DQK-048", "DQK-052", "DQK-053", "DQK-056"),
        outputs=("ipfs_datasets_py/duckdb_control/self_improvement.py", "tests/integration/test_duckdb_self_improvement.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_self_improvement.py",),
        acceptance=("Findings cannot bypass DQP planning/acceptance policy", "Duplicate or stale findings do not create task storms", "The loop uses DuckDB authority rather than Markdown objective refill", "Cross-repository proposals bind separate immutable Git trees and receipt identities"),
        track="rollout",
    ),
    _task(
        "DQK-055", "DQK-G1100", "Complete cutover and scan for residual file authorities",
        "Execute the final producer/consumer scan, prove every mutable file artifact is removed or a declared projection, freeze migration receipts, verify restore/security/performance gates, and publish deterministic release exports.",
        depends_on=("DQK-043", "DQK-045", "DQK-048", "DQK-050", "DQK-051", "DQK-053", "DQK-054", "DQK-058", "DQK-061", "DQK-064", "DQK-067", "DQK-070", "DQK-073", "DQK-076", "DQK-079", "DQK-081", "DQK-101"),
        outputs=("scripts/validation/validate_duckdb_quack_cutover.py", "tests/e2e/test_duckdb_quack_cutover.py"),
        validations=("python -m pytest -q tests/e2e/test_duckdb_quack_cutover.py",),
        acceptance=("Zero undeclared mutable Markdown/JSON/JSONL or Parquet-sidecar authorities remain", "All domain and DuckLake snapshots and receipts verify", "Quack and DuckLake remain replaceable and upgrade-gated", "Final Markdown/JSON artifacts are reproducible exports only"),
        track="rollout",
        priority="P0",
    ),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _repository_tree_id() -> str:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    return f"repository:git-commit:{commit}:tree:{tree}"


def _repository_binding_parts(repository_tree_id: str) -> tuple[str, str] | None:
    prefix = "repository:git-commit:"
    separator = ":tree:"
    if repository_tree_id.startswith(prefix) and separator in repository_tree_id:
        commit, tree = repository_tree_id[len(prefix) :].split(separator, 1)
        if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) and re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", tree
        ):
            return commit, tree
        return None
    legacy_prefix = "tree:git:"
    if repository_tree_id.startswith(legacy_prefix):
        commit = repository_tree_id[len(legacy_prefix) :]
        return (
            (commit, "")
            if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit)
            else None
        )
    return None


def _repository_binding_is_ancestor(repository_tree_id: str) -> bool:
    parts = _repository_binding_parts(repository_tree_id)
    if parts is None:
        return False
    commit, expected_tree = parts
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    if expected_tree:
        try:
            return _git("rev-parse", f"{commit}^{{tree}}") == expected_tree
        except RuntimeError:
            return False
    return True


_MERGE_CANDIDATE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/merge-candidate@2"
)
_MERGE_TARGET_BINDING_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/merge-target-binding@1"
)
_RELEASE_GATE_RECEIPT_SCHEMA = (
    "ipfs_datasets_py/accelerate-release-gate-receipt@1"
)
_RELEASE_VERIFICATION_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/duckdb-quack-release-verification@1"
)
_TASK_SOURCE_CAS_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/task-source-cas@1"
)
_PARALLEL_ACCEPTANCE_RECEIPT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/parallel-acceptance-receipt@1"
)
_PARALLEL_ACCEPTANCE_REQUIREMENT_ID = (
    "185033715568272291470322170325431455647"
)
_POST_MERGE_EVIDENCE_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/post-merge-evidence@1"
)
_POST_MERGE_EVIDENCE_REQUIREMENT_ID = (
    "post-merge-semantic-proof-evidence:ASI-109"
)
_MAX_REPOSITORY_ADMISSION_ROWS = 100_000
_MAX_MERGE_INTEGRATED_RECEIPTS = 4_096


def _strict_json_object(value: Any, *, noun: str) -> dict[str, Any]:
    """Decode one bounded authority object without duplicate keys or NaN."""

    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 2 * 1024 * 1024
    ):
        raise RuntimeError(f"{noun} must be a bounded JSON object")

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise RuntimeError(f"{noun} contains duplicate key {key!r}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> Any:
        raise RuntimeError(f"{noun} contains non-finite value {constant}")

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{noun} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{noun} must contain one JSON object")
    return decoded


def _repository_authority_types() -> tuple[Any, Any, Any]:
    """Import the bridge types used to authenticate restart evidence."""

    selected = str(ACCELERATE_ROOT)
    if selected not in sys.path:
        sys.path.insert(0, selected)
    try:
        from ipfs_accelerate_py.agent_supervisor.task_sources.task_source import (
            TaskSourceIdentity,
        )
    except ImportError:
        from ipfs_accelerate_py.agent_supervisor.task_source import (
            TaskSourceIdentity,
        )
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
        DuckDBTaskCompletionEvidence,
        PortalImplementationDaemon,
    )

    return (
        TaskSourceIdentity,
        DuckDBTaskCompletionEvidence,
        PortalImplementationDaemon,
    )


def _repository_merge_integrated_type() -> Any:
    """Import the producer-owned pre-task-CAS receipt type."""

    selected = str(ACCELERATE_ROOT)
    if selected not in sys.path:
        sys.path.insert(0, selected)
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
        DuckDBMergeIntegratedReceipt,
    )

    return DuckDBMergeIntegratedReceipt


def _repository_content_identity(value: Mapping[str, Any]) -> str:
    try:
        from ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts import (
            content_identity,
        )
    except ImportError:
        from ipfs_accelerate_py.agent_supervisor.formal_verification_contracts import (
            content_identity,
        )

    return str(content_identity(value))


def _repository_parallel_acceptance_type() -> Any:
    try:
        from ipfs_accelerate_py.agent_supervisor.merge.merge_train import (
            ParallelAcceptanceReceipt,
        )
    except ImportError:
        from ipfs_accelerate_py.agent_supervisor.merge_train import (
            ParallelAcceptanceReceipt,
        )

    return ParallelAcceptanceReceipt


def _repository_acceptance_validation_receipt_ids(
    value: Mapping[str, Any],
) -> tuple[str, ...]:
    module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.merge.merge_train",
        "ipfs_accelerate_py.agent_supervisor.merge_train",
    )
    return tuple(module.MergeTrain._validation_receipt_ids(value))


def _repository_post_merge_evidence_type() -> Any:
    module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.evidence.code_evidence_graph",
        "ipfs_accelerate_py.agent_supervisor.code_evidence_graph",
    )
    return module.PostMergeEvidenceReceipt


def _repository_task_source_identity(source: Any, snapshot: Any) -> dict[str, Any]:
    TaskSourceIdentity, _Evidence, _Daemon = _repository_authority_types()
    identity = getattr(source, "identity", None)
    if identity is not None and callable(getattr(identity, "to_dict", None)):
        record = identity.to_dict()
    else:
        source_path = Path(
            getattr(source, "path", getattr(source, "database_path", DATABASE_PATH))
        ).absolute()
        record = TaskSourceIdentity(
            source_kind="duckdb",
            locator=str(source_path),
            source_id=str(snapshot.projection_cid),
            root_id=str(snapshot.plan_root_cid),
            source_schema=str(snapshot.source_schema),
            schema_version=int(snapshot.schema_version),
            repository_root_id=str(snapshot.repository_tree_id),
        ).to_dict()
    return TaskSourceIdentity.from_dict(record).to_dict()


def _repository_task_source_writer(source: Any) -> tuple[str, int] | None:
    backend = getattr(source, "backend", source)
    current = getattr(backend, "current_writer_fence", None)
    if not callable(current):
        return None
    writer = current()
    writer_id = str(getattr(writer, "writer_id", "") or "").strip()
    fencing_token = getattr(writer, "fencing_token", 0)
    if (
        not writer_id
        or isinstance(fencing_token, bool)
        or not isinstance(fencing_token, int)
        or fencing_token < 1
    ):
        raise RuntimeError("task source returned an invalid current writer fence")
    return writer_id, fencing_token


def _repository_task_authority(source: Any) -> dict[str, Any]:
    """Read the task/event authority once and validate typed completion evidence."""

    snapshot, tables, _counts = _consistent_rows(source, ("tasks", "task_events"))
    source_identity = _repository_task_source_identity(source, snapshot)
    _TaskSourceIdentity, Evidence, _Daemon = _repository_authority_types()
    tasks_by_cid = {
        str(row.get("task_cid") or ""): {
            "task_alias": str(row.get("task_alias") or ""),
            "status": str(row.get("status") or ""),
            "revision": _safe_int(row.get("revision"), 0),
        }
        for row in tables["tasks"]
    }
    if "" in tasks_by_cid or any(
        not row["task_alias"] or row["revision"] < 1
        for row in tasks_by_cid.values()
    ):
        raise RuntimeError("task authority contains an invalid CID, alias, or revision")
    aliases = [row["task_alias"] for row in tasks_by_cid.values()]
    if len(aliases) != len(set(aliases)):
        raise RuntimeError("task authority contains a duplicated task alias")
    release_task_cids = {
        task_cid
        for task_cid, row in tasks_by_cid.items()
        if row["task_alias"] == RELEASE_GATE_TASK_ID
    }
    if len(release_task_cids) != 1:
        raise RuntimeError("release gate task identity is missing or ambiguous")

    completion_by_merge: dict[str, list[dict[str, Any]]] = {}
    completion_by_request: dict[str, list[dict[str, Any]]] = {}
    release_receipts: dict[str, list[dict[str, Any]]] = {}
    manual_gate_receipts: dict[str, list[dict[str, Any]]] = {
        task_id: [] for task_id in MANUAL_GATE_TASK_IDS
    }
    for row in sorted(
        tables["task_events"], key=lambda item: _safe_int(item.get("sequence"), 0)
    ):
        if str(row.get("event_type") or "") != "status_changed":
            continue
        body = _strict_json_object(
            row.get("body_json"), noun=f"task event {row.get('event_cid') or '?'}"
        )
        task_cid = str(row.get("task_cid") or "")
        if body.get("task_cid") != task_cid or task_cid not in tasks_by_cid:
            raise RuntimeError("status event task identity is stale or foreign")
        if body.get("status") != "completed":
            continue
        if (
            body.get("schema") != _TASK_SOURCE_CAS_SCHEMA
            or str(row.get("event_cid") or "")
            != _repository_content_identity(body)
            or _safe_int(body.get("task_revision"), 0) < 2
        ):
            raise RuntimeError("completed status event identity is invalid")
        current_task = tasks_by_cid[task_cid]
        if (
            current_task["status"] != "completed"
            or _safe_int(body.get("task_revision"), 0)
            != current_task["revision"]
        ):
            continue
        receipt = body.get("receipt")
        if not isinstance(receipt, Mapping):
            continue
        receipt_record = dict(receipt)
        task_alias = tasks_by_cid[task_cid]["task_alias"]
        if (
            task_alias in MANUAL_GATE_TASK_IDS
            and receipt_record.get("schema") == MANUAL_GATE_CAS_RECEIPT_SCHEMA
        ):
            manual_gate_receipts[task_alias].append(
                {
                    "event_cid": str(row.get("event_cid") or ""),
                    "receipt": receipt_record,
                }
            )
        if task_cid in release_task_cids and receipt_record.get("schema") == _RELEASE_GATE_RECEIPT_SCHEMA:
            superproject_commit = str(
                receipt_record.get("superproject_commit") or ""
            ).strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", superproject_commit):
                raise RuntimeError("release acknowledgement has no full superproject commit")
            release_receipts.setdefault(superproject_commit, []).append(
                {
                    "event_cid": str(row.get("event_cid") or ""),
                    "receipt": receipt_record,
                }
            )

        raw_evidence = receipt_record.get("completion_evidence")
        if raw_evidence is None:
            continue
        if receipt_record.get("operation") != "mark_task_completed":
            raise RuntimeError("completion evidence has a foreign task operation")
        if not isinstance(raw_evidence, Mapping):
            raise RuntimeError("completion evidence is not an object")
        evidence = Evidence.from_dict(raw_evidence)
        if (
            receipt_record.get("task_source_identity_id")
            != source_identity["identity_id"]
            or raw_evidence.get("evidence_id") != evidence.evidence_id
            or evidence.task_cid != task_cid
            or evidence.task_source_identity_id != source_identity["identity_id"]
        ):
            raise RuntimeError("completion evidence is detached from task-source authority")
        record = {
            "event_cid": str(row.get("event_cid") or ""),
            "task_alias": tasks_by_cid[task_cid]["task_alias"],
            "evidence": evidence,
        }
        completion_by_merge.setdefault(evidence.merge_commit, []).append(record)
        completion_by_request.setdefault(evidence.merge_request_id, []).append(record)

    return {
        "snapshot": snapshot,
        "source_identity": source_identity,
        "source_writer": _repository_task_source_writer(source),
        "tasks_by_cid": tasks_by_cid,
        "tasks_by_alias": {
            row["task_alias"]: {"task_cid": task_cid, **row}
            for task_cid, row in tasks_by_cid.items()
        },
        "completion_by_merge": completion_by_merge,
        "completion_by_request": completion_by_request,
        "release_receipts": release_receipts,
        "manual_gate_receipts": manual_gate_receipts,
    }


def _repository_merge_queue_rows() -> dict[str, dict[str, Any]]:
    database_path = MERGE_QUEUE_ROOT / "merge_queue.duckdb"
    if not database_path.is_file():
        return {}
    if database_path.is_symlink():
        raise RuntimeError("merge-queue authority database must not be a symlink")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB is required to verify merge-queue authority") from exc
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        raw_rows = connection.execute(
            """SELECT request_id, branch_name, task_id, attempt, metadata_json,
                      commit_sha, canonical_task_id, canonical_task_key, status,
                      claimed_at, consumer_id, claim_token, claim_generation,
                      failure_count, finished_at
                 FROM merge_requests
                ORDER BY request_id
                LIMIT ?""",
            [_MAX_REPOSITORY_ADMISSION_ROWS + 1],
        ).fetchall()
    except Exception as exc:
        raise RuntimeError("merge-queue authority schema is unavailable") from exc
    finally:
        connection.close()
    if len(raw_rows) > _MAX_REPOSITORY_ADMISSION_ROWS:
        raise RuntimeError("merge-queue authority exceeds its restart admission bound")
    columns = (
        "request_id",
        "branch_name",
        "task_id",
        "attempt",
        "metadata_json",
        "commit_sha",
        "canonical_task_id",
        "canonical_task_key",
        "status",
        "claimed_at",
        "consumer_id",
        "claim_token",
        "claim_generation",
        "failure_count",
        "finished_at",
    )
    rows: dict[str, dict[str, Any]] = {}
    for raw_row in raw_rows:
        row = dict(zip(columns, raw_row, strict=True))
        request_id = str(row["request_id"] or "").strip()
        if not request_id or request_id in rows:
            raise RuntimeError("merge-queue request identity is empty or duplicated")
        row["metadata"] = _strict_json_object(
            row.pop("metadata_json"), noun=f"merge request {request_id} metadata"
        )
        rows[request_id] = row
    return rows


def _repository_merge_integrated_receipts() -> tuple[Any, ...]:
    """Strictly restore a bounded snapshot of producer receipt artifacts.

    The queue root is external mutable state.  Walking only the two expected
    directory components, rejecting links, and comparing directory identities
    before and after the scan prevents a replaced ancestor from redirecting
    restart admission to an attacker-controlled receipt set.
    """

    import stat as stat_module

    paths = (
        MERGE_QUEUE_ROOT,
        MERGE_QUEUE_ROOT / "train",
        MERGE_QUEUE_ROOT / "train" / "receipts",
    )
    identities: list[tuple[int, int]] = []
    for index, path in enumerate(paths):
        try:
            path_stat = os.lstat(path)
        except FileNotFoundError:
            if index > 0:
                return ()
            raise RuntimeError("merge-receipt queue root is unavailable") from None
        except OSError as exc:
            raise RuntimeError("merge-receipt path is unavailable") from exc
        if not stat_module.S_ISDIR(path_stat.st_mode):
            raise RuntimeError(
                "merge-receipt path contains a symlink or non-directory ancestor"
            )
        identities.append((path_stat.st_dev, path_stat.st_ino))

    receipt_directory = paths[-1]
    try:
        with os.scandir(receipt_directory) as entries:
            names = sorted(
                entry.name
                for entry in entries
                if entry.name.startswith("merge-integrated-")
                and entry.name.endswith(".json")
            )
    except OSError as exc:
        raise RuntimeError("merge-integrated receipt directory is unreadable") from exc
    if len(names) > _MAX_MERGE_INTEGRATED_RECEIPTS:
        raise RuntimeError("merge-integrated receipt scan exceeds its bound")

    Receipt = _repository_merge_integrated_type()
    restored: list[Any] = []
    receipt_ids: set[str] = set()
    for name in names:
        try:
            receipt = Receipt.load_file(receipt_directory / name)
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"merge-integrated receipt {name!r} is invalid"
            ) from exc
        if receipt.receipt_id in receipt_ids:
            raise RuntimeError("merge-integrated receipt authority is ambiguous")
        receipt_ids.add(receipt.receipt_id)
        restored.append(receipt)

    for path, identity in zip(paths, identities, strict=True):
        try:
            path_stat = os.lstat(path)
        except OSError as exc:
            raise RuntimeError("merge-receipt path changed during scan") from exc
        if (
            not stat_module.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != identity
        ):
            raise RuntimeError("merge-receipt path changed during scan")
    return tuple(restored)


def _repository_id() -> str:
    selected = str(ACCELERATE_ROOT)
    if selected not in sys.path:
        sys.path.insert(0, selected)
    try:
        from ipfs_accelerate_py.agent_supervisor.merge.checkout_lock import (
            checkout_repository_id,
        )
    except ImportError:
        from ipfs_accelerate_py.agent_supervisor.checkout_lock import (
            checkout_repository_id,
        )

    return str(checkout_repository_id(REPO_ROOT))


def _git_commit_parents(commit: str) -> tuple[str, ...]:
    fields = _git("rev-list", "--parents", "-n", "1", commit).split()
    if not fields or fields[0] != commit:
        raise RuntimeError(f"could not resolve parents for commit {commit}")
    return tuple(fields[1:])


def _git_commit_tree(commit: str) -> str:
    tree = _git("rev-parse", f"{commit}^{{tree}}").lower()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree):
        raise RuntimeError(f"commit {commit} has no full Git tree")
    return tree


def _git_changed_paths(parent: str, commit: str) -> tuple[str, ...]:
    return tuple(
        path.strip()
        for path in _git("diff", "--name-only", parent, commit).splitlines()
        if path.strip()
    )


def _git_changed_submodule_paths(parent: str, commit: str) -> tuple[str, ...]:
    """Return paths whose first-parent delta adds, removes, or changes a gitlink."""

    result = subprocess.run(
        ["git", "diff", "--raw", "--no-renames", parent, commit],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("could not inspect merge submodule changes")
    paths: list[str] = []
    for line in result.stdout.splitlines():
        header, separator, path = line.partition("\t")
        fields = header.split()
        if (
            not separator
            or len(fields) < 2
            or not fields[0].startswith(":")
        ):
            raise RuntimeError("Git returned a malformed raw merge delta")
        if fields[0][1:] == "160000" or fields[1] == "160000":
            paths.append(path)
    return tuple(paths)


def _git_blob(commit: str, path: str, *, maximum_bytes: int = 16 * 1024 * 1024) -> bytes:
    size_text = _git("cat-file", "-s", f"{commit}:{path}")
    size = int(size_text)
    if size < 1 or size > maximum_bytes:
        raise RuntimeError(f"export blob {path} exceeds its admission bound")
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode or len(result.stdout) != size:
        raise RuntimeError(f"could not read exact export blob {path}")
    return result.stdout


def _repository_export_paths() -> dict[str, str]:
    paths: dict[str, str] = {}
    for kind, selected in (
        ("markdown", DEFAULT_MARKDOWN_EXPORT),
        ("json", DEFAULT_JSON_EXPORT),
    ):
        try:
            relative = selected.resolve().relative_to(REPO_ROOT.resolve())
        except ValueError:
            continue
        paths[str(relative)] = kind
    return paths


def _repository_export_commit_is_valid(commit: str, paths: Sequence[str]) -> bool:
    allowed = _repository_export_paths()
    if not paths or set(paths).difference(allowed):
        return False
    for path in paths:
        raw = _git_blob(commit, path)
        if allowed[path] == "markdown":
            try:
                rendered = raw.decode("utf-8")
            except UnicodeDecodeError:
                return False
            match = re.search(
                r"\n<!-- rendered-body-sha256: ([0-9a-f]{64}) -->\n?\Z",
                rendered,
            )
            if (
                match is None
                or "Generated projection only" not in rendered[: match.start()]
                or _sha256_text(rendered[: match.start()]) != match.group(1)
            ):
                return False
        else:
            try:
                payload = _strict_json_object(raw.decode("utf-8"), noun="JSON export")
            except (RuntimeError, UnicodeDecodeError):
                return False
            claimed = str(payload.pop("export_digest", ""))
            if (
                payload.get("schema")
                != "ipfs_datasets_py/duckdb-quack-plan-export@1"
                or claimed != f"sha256:{_sha256_text(_canonical_json(payload))}"
            ):
                return False
    return True


def _repository_queue_metadata_binding(
    row: Mapping[str, Any],
    *,
    implementation_commit: str,
    task_cid: str,
    task_alias: str,
    source_identity: Mapping[str, Any],
) -> tuple[tuple[str, ...], str, Mapping[str, Any]]:
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        raise RuntimeError("merge request metadata is missing")
    if metadata.get("bundle_work_order") is not None:
        raise RuntimeError(
            "launch_blocker=typed_bundle_completion_receipt_set_missing"
        )
    if (
        metadata.get("schema") != _MERGE_CANDIDATE_SCHEMA
        or metadata.get("target_binding_schema") != _MERGE_TARGET_BINDING_SCHEMA
        or str(metadata.get("target_repository_id") or "") != _repository_id()
        or str(metadata.get("target_branch") or "") != TARGET_BRANCH
        or str(row.get("commit_sha") or "").lower() != implementation_commit
        or str(metadata.get("implementation_commit") or "").lower()
        != implementation_commit
        or str(row.get("canonical_task_id") or "") != task_cid
        or str(metadata.get("canonical_task_cid") or "") != task_cid
        or str(row.get("task_id") or "") != task_alias
    ):
        raise RuntimeError("merge request target, task, or implementation binding is foreign")
    task_record = metadata.get("task")
    if not isinstance(task_record, Mapping) or task_record.get("task_id") != task_alias:
        raise RuntimeError("merge request task projection is detached")
    canonical_key = str(row.get("canonical_task_key") or "").strip()
    if (
        not canonical_key
        or str(metadata.get("canonical_task_key") or "") != canonical_key
    ):
        raise RuntimeError("merge request canonical task key is missing or stale")
    candidate_tree = _git_commit_tree(implementation_commit)
    if str(metadata.get("candidate_tree") or "").lower() != candidate_tree:
        raise RuntimeError("merge request candidate tree is stale")
    raw_identity = metadata.get("task_source_identity")
    if not isinstance(raw_identity, Mapping):
        raise RuntimeError("merge request task-source identity is missing")
    TaskSourceIdentity, _Evidence, Daemon = _repository_authority_types()
    queued_identity = TaskSourceIdentity.from_dict(raw_identity).to_dict()
    if (
        dict(raw_identity) != dict(source_identity)
        or queued_identity != dict(source_identity)
    ):
        raise RuntimeError("merge request task-source identity is foreign")
    writer = metadata.get("task_source_writer")
    if not isinstance(writer, Mapping):
        raise RuntimeError("merge request task-source writer fence is missing")
    writer_id = str(writer.get("writer_id") or "").strip()
    writer_fence = writer.get("fencing_token")
    if (
        not writer_id
        or isinstance(writer_fence, bool)
        or not isinstance(writer_fence, int)
        or writer_fence < 1
        or set(writer) != {"writer_id", "fencing_token"}
    ):
        raise RuntimeError("merge request task-source writer fence is invalid")
    validation_receipt_ids, proposal_receipt_id = (
        Daemon._merge_completion_receipt_binding(metadata)
    )
    validation = metadata.get("validation_proof")
    execution = (
        validation.get("validation_execution_receipt")
        if isinstance(validation, Mapping)
        else None
    )
    if (
        not isinstance(execution, Mapping)
        or str(execution.get("receipt_id") or "") not in validation_receipt_ids
    ):
        raise RuntimeError("merge request validation execution receipt is not explicit")
    return validation_receipt_ids, proposal_receipt_id, writer


def _repository_parallel_acceptance_receipt(
    row: Mapping[str, Any],
    *,
    request_id: str,
    task_cid: str,
    task_alias: str,
    implementation_commit: str,
    merge_commit: str,
    merge_tree: str,
) -> Any:
    metadata = row.get("metadata")
    completion = metadata.get("completion") if isinstance(metadata, Mapping) else None
    if not isinstance(completion, Mapping):
        raise RuntimeError("completed queue row has no typed completion binding")
    allowed_completion_fields = {
        "acceptance_receipt_id",
        "requirement_id",
        "target_commit",
        "post_merge_evidence_receipt_id",
        "post_merge_evidence_requirement_id",
    }
    if set(completion).difference(allowed_completion_fields):
        raise RuntimeError("queue completion contains unsupported authority fields")
    evidence_fields = {
        "post_merge_evidence_receipt_id",
        "post_merge_evidence_requirement_id",
    }
    present_evidence = evidence_fields.intersection(completion)
    if (
        present_evidence != evidence_fields
        or any(
            not str(completion.get(field) or "").strip()
            for field in evidence_fields
        )
    ):
        raise RuntimeError(
            "launch_blocker=post_merge_evidence_completion_binding_missing"
        )
    receipt_id = str(completion.get("acceptance_receipt_id") or "").strip()
    match = re.fullmatch(r"sha256:([0-9a-f]{64})", receipt_id)
    if match is None:
        raise RuntimeError("queue completion has no content-addressed acceptance receipt")
    if (
        completion.get("requirement_id") != _PARALLEL_ACCEPTANCE_REQUIREMENT_ID
        or str(completion.get("target_commit") or "").lower() != merge_commit
    ):
        raise RuntimeError("queue completion target or requirement is foreign")
    receipt_path = (
        MERGE_QUEUE_ROOT
        / "train"
        / "receipts"
        / f"acceptance-{match.group(1)}.json"
    )
    if (
        receipt_path.is_symlink()
        or not receipt_path.is_file()
        or receipt_path.stat().st_size < 1
        or receipt_path.stat().st_size > 2 * 1024 * 1024
    ):
        raise RuntimeError("parallel acceptance receipt projection is unavailable")
    payload = _strict_json_object(
        receipt_path.read_text(encoding="utf-8"),
        noun="parallel acceptance receipt",
    )
    Receipt = _repository_parallel_acceptance_type()
    receipt = Receipt.from_dict(payload)
    if _canonical_json(payload) != _canonical_json(receipt.to_dict()):
        raise RuntimeError("parallel acceptance receipt contains unsupported fields")
    validation = receipt.post_merge_validation
    validated_commit = str(
        validation.get("validated_commit")
        or validation.get("target_commit")
        or ""
    ).lower()
    integration = receipt.integration
    token_digest = str(receipt.mutation_fence_token_digest or "")
    evidence_payload = validation.get("post_merge_evidence_receipt")
    evidence_wrapper = validation.get("post_merge_evidence")
    if not isinstance(evidence_payload, Mapping) or not isinstance(
        evidence_wrapper, Mapping
    ):
        raise RuntimeError(
            "launch_blocker=post_merge_evidence_receipt_missing_from_acceptance"
        )
    EvidenceReceipt = _repository_post_merge_evidence_type()
    post_merge_evidence = EvidenceReceipt.from_dict(evidence_payload)
    if _canonical_json(evidence_payload) != _canonical_json(
        post_merge_evidence.to_dict()
    ):
        raise RuntimeError("post-merge evidence projection is noncanonical")
    post_merge_receipt_id = str(post_merge_evidence.receipt_id or "")
    metadata = row["metadata"]
    policy_record = metadata.get("formal_verification_policy")
    expected_policy_id = str(metadata.get("policy_id") or "").strip()
    if not expected_policy_id and isinstance(policy_record, Mapping):
        expected_policy_id = str(policy_record.get("policy_id") or "").strip()
    candidate_tree_id = f"git-tree:{_git_commit_tree(implementation_commit)}"
    merged_tree_id = f"git-tree:{merge_tree}"
    validation_ids = tuple(receipt.validation_receipt_ids)
    derived_validation_ids = _repository_acceptance_validation_receipt_ids(
        validation
    )
    validation_projection_ids = validation.get("validation_receipt_ids")
    if not isinstance(validation_projection_ids, Sequence) or isinstance(
        validation_projection_ids, (str, bytes, bytearray)
    ):
        validation_projection_ids = ()
    expected_evidence_wrapper_fields = {
        "passed",
        "reason",
        "reason_codes",
        "receipt",
        "receipt_id",
        "repository_tree_id",
        "merge_commit",
    }
    if (
        receipt.schema != _PARALLEL_ACCEPTANCE_RECEIPT_SCHEMA
        or receipt.requirement_id != _PARALLEL_ACCEPTANCE_REQUIREMENT_ID
        or receipt.receipt_id != receipt_id
        or receipt.request_id != request_id
        or receipt.canonical_task_id != task_cid
        or receipt.candidate_commit.lower() != implementation_commit
        or receipt.target_commit.lower() != merge_commit
        or receipt.accepted is not True
        or receipt.preflight.get("passed") is not True
        or validation.get("passed") is not True
        or validated_commit != merge_commit
        or integration.get("integrated") is not True
        or str(integration.get("request_id") or "") != request_id
        or str(integration.get("canonical_task_id") or "") != task_cid
        or str(integration.get("target_commit") or "").lower() != merge_commit
        or str(integration.get("commit_sha") or "").lower()
        != implementation_commit
        or not re.fullmatch(r"[0-9a-f]{64}", post_merge_receipt_id)
        or post_merge_receipt_id not in derived_validation_ids
        or validation_ids != derived_validation_ids
        or tuple(validation_projection_ids) != derived_validation_ids
        or completion.get("post_merge_evidence_receipt_id")
        != post_merge_receipt_id
        or completion.get("post_merge_evidence_requirement_id")
        != _POST_MERGE_EVIDENCE_REQUIREMENT_ID
        or evidence_payload.get("schema") != _POST_MERGE_EVIDENCE_SCHEMA
        or set(evidence_wrapper) != expected_evidence_wrapper_fields
        or evidence_wrapper.get("passed") is not True
        or str(evidence_wrapper.get("reason") or "")
        or evidence_wrapper.get("receipt_id") != post_merge_receipt_id
        or _canonical_json(evidence_wrapper.get("receipt"))
        != _canonical_json(evidence_payload)
        or str(evidence_wrapper.get("repository_tree_id") or "")
        != merged_tree_id
        or str(evidence_wrapper.get("merge_commit") or "").lower()
        != merge_commit
        or tuple(evidence_wrapper.get("reason_codes") or ())
        or post_merge_evidence.receipt_id != post_merge_receipt_id
        or post_merge_evidence.repository_id != _repository_id()
        or post_merge_evidence.task_id != task_alias
        or not expected_policy_id
        or post_merge_evidence.policy_id != expected_policy_id
        or post_merge_evidence.candidate_tree_id != candidate_tree_id
        or post_merge_evidence.merged_tree_id != merged_tree_id
        or post_merge_evidence.verified_tree_id != merged_tree_id
        or post_merge_evidence.merge_commit_id.lower() != merge_commit
        or post_merge_evidence.accepted is not True
        or post_merge_evidence.authoritative is not True
        or post_merge_evidence.merge_authoritative is not True
        or post_merge_evidence.completion_authoritative is not True
        or post_merge_evidence.freshness_authoritative is not True
        or tuple(post_merge_evidence.proved_requirement_ids)
        != (_POST_MERGE_EVIDENCE_REQUIREMENT_ID,)
        or tuple(post_merge_evidence.reason_codes)
        or not str(receipt.mutation_fence_owner or "").strip()
        or receipt.mutation_fence_generation < 1
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", token_digest)
    ):
        raise RuntimeError("parallel acceptance receipt is stale, incomplete, or foreign")
    return receipt


def _repository_completed_merge_is_valid(
    commit: str,
    parents: Sequence[str],
    tree: str,
    *,
    authority: Mapping[str, Any],
    queue_rows: Mapping[str, Mapping[str, Any]],
    admitted_requests: set[str],
    admitted_task_cids: set[str],
) -> tuple[bool, str, bool]:
    records = authority["completion_by_merge"].get(commit, ())
    if len(records) != 1:
        request_ids = {
            record["evidence"].merge_request_id
            for record in records
        }
        if len(request_ids) == 1:
            bundle_row = queue_rows.get(next(iter(request_ids)))
            bundle_metadata = (
                bundle_row.get("metadata")
                if isinstance(bundle_row, Mapping)
                else None
            )
            if isinstance(bundle_metadata, Mapping) and bundle_metadata.get(
                "bundle_work_order"
            ) is not None:
                return (
                    False,
                    "launch_blocker=typed_bundle_completion_receipt_set_missing",
                    False,
                )
        return False, "task completion evidence is missing or ambiguous", False
    matches: list[str] = []
    failures: list[str] = []
    for record in records:
        evidence = record["evidence"]
        request_id = evidence.merge_request_id
        row = queue_rows.get(request_id)
        if row is None:
            failures.append(f"{request_id}: queue receipt missing")
            continue
        try:
            if (
                evidence.implementation_commit != parents[1]
                or evidence.target_tree != tree
                or request_id in admitted_requests
                or len(authority["completion_by_request"].get(request_id, ())) != 1
            ):
                raise RuntimeError("completion evidence commit or request was reused")
            validation_ids, proposal_id, writer = _repository_queue_metadata_binding(
                row,
                implementation_commit=parents[1],
                task_cid=evidence.task_cid,
                task_alias=str(record["task_alias"]),
                source_identity=authority["source_identity"],
            )
            status = str(row.get("status") or "")
            if (
                tuple(validation_ids) != evidence.validation_receipt_ids
                or proposal_id != evidence.proposal_receipt_id
                or str(writer.get("writer_id") or "")
                != evidence.task_source_writer_id
                or writer.get("fencing_token")
                != evidence.task_source_fencing_token
            ):
                raise RuntimeError("queue row does not bind exact task completion evidence")
            if status == "completed":
                acceptance = _repository_parallel_acceptance_receipt(
                    row,
                    request_id=request_id,
                    task_cid=evidence.task_cid,
                    task_alias=str(record["task_alias"]),
                    implementation_commit=parents[1],
                    merge_commit=commit,
                    merge_tree=tree,
                )
                if (
                    float(row.get("finished_at") or 0) <= 0
                    or float(row.get("claimed_at") or 0) != 0
                    or str(row.get("consumer_id") or "")
                    or str(row.get("claim_token") or "")
                    or _safe_int(row.get("claim_generation"), 0)
                    != acceptance.mutation_fence_generation + 1
                ):
                    raise RuntimeError("completed queue fence does not match acceptance")
                matches.append(f"completed:{request_id}")
                continue
            if status == "processing":
                if (
                    float(row.get("finished_at") or 0) != 0
                    or float(row.get("claimed_at") or 0) <= 0
                    or row["metadata"].get("completion") is not None
                    or str(row.get("consumer_id") or "")
                    != evidence.merge_consumer_id
                    or str(row.get("claim_token") or "") != evidence.lease_id
                    or _safe_int(row.get("claim_generation"), 0)
                    != evidence.fencing_token
                    or authority.get("source_writer")
                    != (
                        evidence.task_source_writer_id,
                        evidence.task_source_fencing_token,
                    )
                ):
                    raise RuntimeError("processing queue claim is not the completion CAS claim")
                matches.append(f"processing:{request_id}")
                continue
            raise RuntimeError("task completion evidence has no admissible queue state")
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            failures.append(f"{request_id}: {exc}")
            continue
    if len(matches) != 1:
        detail = "; ".join(failures[:3]) or "no task completion evidence"
        return False, detail, False
    mode, request_id = matches[0].split(":", 1)
    admitted_requests.add(request_id)
    admitted_task_cids.add(records[0]["evidence"].task_cid)
    return True, request_id, mode == "processing"


def _repository_pending_tip_is_valid(
    commit: str,
    parents: Sequence[str],
    *,
    authority: Mapping[str, Any],
    queue_rows: Mapping[str, Mapping[str, Any]],
    source: Any,
) -> tuple[bool, str]:
    """Admit only one current tip explained by a durable producer receipt.

    This is a read-only restart explanation for the post-Git/pre-task-CAS
    crash window.  It never repairs the queue or task source.  All mutable
    authorities are reread after receipt restoration so a stale or requeued
    claim cannot borrow an older receipt.
    """

    active_rows = [
        row
        for row in queue_rows.values()
        if str(row.get("status") or "") in {"pending", "processing"}
        and str(row.get("commit_sha") or "").lower() == parents[1]
    ]
    if len(active_rows) != 1:
        return False, "active merge request is missing or ambiguous"

    row = active_rows[0]
    request_id = str(row.get("request_id") or "")
    task_cid = str(row.get("canonical_task_id") or "")
    task = authority["tasks_by_cid"].get(task_cid)
    try:
        if task is None:
            raise RuntimeError("active merge task is absent")
        validation_ids, proposal_id, writer = _repository_queue_metadata_binding(
            row,
            implementation_commit=parents[1],
            task_cid=task_cid,
            task_alias=str(task["task_alias"]),
            source_identity=authority["source_identity"],
        )
        metadata = row["metadata"]
        changed_submodules = metadata.get("changed_submodule_paths")
        if (
            isinstance(changed_submodules, Sequence)
            and not isinstance(changed_submodules, (str, bytes, bytearray))
            and any(str(item or "").strip() for item in changed_submodules)
        ):
            raise RuntimeError(
                "launch_blocker=typed_compound_integration_receipt_set_missing"
            )
        if (
            metadata.get("completion") is not None
            or float(row.get("finished_at") or 0) != 0
        ):
            raise RuntimeError("active merge request already has terminal metadata")
        source_writer = authority.get("source_writer")
        if source_writer is None or source_writer != (
            str(writer.get("writer_id") or ""),
            writer.get("fencing_token"),
        ):
            raise RuntimeError("active merge request writer fence is not current")
        if (
            authority["completion_by_merge"].get(commit)
            or authority["completion_by_request"].get(request_id)
        ):
            raise RuntimeError("active merge request has detached completion evidence")

        status = str(row.get("status") or "")
        if status == "pending":
            if any(
                (
                    float(row.get("claimed_at") or 0) != 0,
                    bool(str(row.get("consumer_id") or "")),
                    bool(str(row.get("claim_token") or "")),
                )
            ):
                raise RuntimeError("pending merge request retains claim state")
            return (
                False,
                f"launch_blocker=unclaimed_pending_merge_request:{request_id}",
            )

        claim_generation = row.get("claim_generation")
        consumer_id = str(row.get("consumer_id") or "").strip()
        claim_token = str(row.get("claim_token") or "").strip()
        if (
            status != "processing"
            or float(row.get("claimed_at") or 0) <= 0
            or not consumer_id
            or not claim_token
            or isinstance(claim_generation, bool)
            or not isinstance(claim_generation, int)
            or claim_generation < 1
        ):
            raise RuntimeError("processing merge request has no live claim")

        tip_receipts = tuple(
            receipt
            for receipt in _repository_merge_integrated_receipts()
            if receipt.merge_commit == commit
        )
        if not tip_receipts:
            return (
                False,
                "launch_blocker=merge_integrated_receipt_missing_before_task_cas:"
                f"{request_id}",
            )
        if len(tip_receipts) != 1:
            raise RuntimeError("merge-integrated receipt authority is ambiguous")
        receipt = tip_receipts[0]

        candidate_tree = _git_commit_tree(parents[1])
        expected = {
            "repository_id": _repository_id(),
            "target_branch": TARGET_BRANCH,
            "request_id": request_id,
            "task_id": str(task["task_alias"]),
            "task_cid": task_cid,
            "task_source_identity_id": authority["source_identity"]["identity_id"],
            "task_source_writer_id": source_writer[0],
            "task_source_fencing_token": source_writer[1],
            "candidate_commit": parents[1],
            "candidate_tree": candidate_tree,
            "merge_commit": commit,
            "merge_tree": _git_commit_tree(commit),
            "merge_parents": tuple(parents),
            "merge_consumer_id": consumer_id,
            "lease_id": claim_token,
            "fencing_token": claim_generation,
            "validation_receipt_ids": tuple(validation_ids),
            "proposal_receipt_id": proposal_id,
        }
        stale_fields = tuple(
            field
            for field, expected_value in expected.items()
            if getattr(receipt, field) != expected_value
        )
        if stale_fields:
            raise RuntimeError(
                "merge-integrated receipt binding is stale: "
                + ",".join(stale_fields)
            )
        if _git_changed_submodule_paths(parents[0], commit):
            raise RuntimeError(
                "launch_blocker=typed_compound_integration_receipt_set_missing"
            )

        # Receipt parsing is not a lock.  Re-read every mutable authority and
        # require the exact claim, task-source generation, writer fence, and
        # Git tip/tree to remain unchanged across the parse.
        current_rows = _repository_merge_queue_rows()
        if current_rows != queue_rows or current_rows.get(request_id) != row:
            raise RuntimeError("merge-integrated queue claim changed at reread")
        snapshot = source.snapshot()
        admitted_snapshot = authority["snapshot"]
        if any(
            getattr(snapshot, field) != getattr(admitted_snapshot, field)
            for field in (
                "plan_root_cid",
                "projection_cid",
                "repository_tree_id",
                "revision",
                "event_cursor",
            )
        ):
            raise RuntimeError("merge-integrated task source changed at reread")
        if (
            _repository_task_source_identity(source, snapshot)
            != authority["source_identity"]
            or _repository_task_source_writer(source) != source_writer
        ):
            raise RuntimeError("merge-integrated source identity or writer changed")
        current_task = source.get_task(str(task["task_alias"]))
        if (
            current_task is None
            or current_task.task_cid != task_cid
            or current_task.status != task["status"]
            or current_task.revision != task["revision"]
        ):
            raise RuntimeError("merge-integrated task binding changed at reread")
        if (
            _git("rev-parse", "HEAD").lower() != commit
            or _git("rev-parse", TARGET_BRANCH).lower() != commit
            or _git_commit_parents(commit) != tuple(parents)
            or _git_commit_tree(parents[1]) != candidate_tree
            or _git_commit_tree(commit) != receipt.merge_tree
            or _git_changed_submodule_paths(parents[0], commit)
        ):
            raise RuntimeError("merge-integrated Git binding changed at reread")
        return True, request_id
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        return False, f"{request_id or '?'}: {exc}"


def _repository_release_commit_is_valid(
    commit: str,
    parent: str,
    *,
    authority: Mapping[str, Any],
    admitted_task_cids: set[str],
) -> tuple[bool, str]:
    if set(_git_changed_paths(parent, commit)) != {"ipfs_accelerate_py"}:
        return False, "release acknowledgement commit is not an isolated gitlink pin"
    verifier_task = authority["tasks_by_alias"].get(RELEASE_VERIFIER_TASK_ID)
    if verifier_task is None or verifier_task.get("status") != "completed":
        return False, "release verifier task is not currently completed"
    if str(verifier_task.get("task_cid") or "") not in admitted_task_cids:
        return False, "release verifier has no receipt-admitted task merge"
    authenticated = authority.get("manual_gate_receipts", {}).get(
        RELEASE_GATE_TASK_ID, ()
    )
    if authenticated:
        if len(authenticated) != 1:
            return False, "authenticated release acknowledgement is ambiguous"
        receipt = authenticated[0]["receipt"]
        gate_task = authority["tasks_by_alias"].get(RELEASE_GATE_TASK_ID)
        if gate_task is None:
            return False, "authenticated release gate task is missing"
        valid, detail = _validate_manual_gate_cas_receipt(
            receipt,
            task_row=gate_task,
            snapshot=authority["snapshot"],
            require_released=True,
            current_writer=authority["source_writer"],
        )
        if not valid:
            return False, f"authenticated release acknowledgement rejected: {detail}"
        execution = receipt["execution"]
        verification = execution["typed_output"]
        verifier_commit = str(execution["verifier"]["repository_commit"]).lower()
        if verifier_commit != commit.lower():
            return False, "release verifier execution is not bound to the pin commit"
        entry = _git("ls-tree", commit, "--", "ipfs_accelerate_py").split()
        if len(entry) < 3 or entry[0:2] != ["160000", "commit"]:
            return False, "authenticated release commit has no accelerator gitlink"
        accelerator_commit = entry[2].lower()
        try:
            accelerator_tree = _git(
                "-C",
                "ipfs_accelerate_py",
                "rev-parse",
                f"{accelerator_commit}^{{tree}}",
            ).lower()
        except RuntimeError:
            return False, "authenticated accelerator release is unavailable locally"
        if (
            str(verification.get("accelerator_commit") or "").lower()
            != accelerator_commit
            or str(verification.get("accelerator_tree") or "").lower()
            != accelerator_tree
        ):
            return False, "authenticated release output is stale for the gitlink"
        return True, f"authenticated manual-gate release: {receipt['receipt_id']}"
    receipts = authority["release_receipts"].get(commit, ())
    if len(receipts) != 1:
        return False, "release acknowledgement receipt is missing or ambiguous"
    receipt = receipts[0]["receipt"]
    expected_receipt_fields = {
        "schema",
        "input_receipt_sha256",
        "verification",
        "verifier_sha256",
        "plan_root_cid",
        "repository_tree_id",
        "superproject_commit",
        "acknowledged_at",
    }
    if set(receipt) != expected_receipt_fields:
        return False, "release acknowledgement fields are incomplete or unsupported"
    verification = receipt.get("verification")
    snapshot = authority["snapshot"]
    required_verification_fields = (
        "accelerator_commit",
        "accelerator_tree",
        "release_receipt_cid",
        "cutover_receipt_cid",
        "store_generation",
        "schema_checksum",
        "quack_profile",
        "expires_at",
        "decision_cid",
    )
    if (
        not isinstance(verification, Mapping)
        or verification.get("schema") != _RELEASE_VERIFICATION_SCHEMA
        or verification.get("accepted") is not True
        or any(
            not isinstance(verification.get(field), str)
            or not str(verification.get(field) or "").strip()
            or len(str(verification.get(field)).encode("utf-8")) > 4096
            or any(character in str(verification.get(field)) for character in ("\0", "\n", "\r"))
            for field in required_verification_fields
        )
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(receipt.get("input_receipt_sha256") or ""),
        )
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(receipt.get("verifier_sha256") or "")
        )
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(verification.get("schema_checksum") or "")
        )
        or receipt.get("plan_root_cid") != snapshot.plan_root_cid
        or receipt.get("repository_tree_id") != snapshot.repository_tree_id
        or str(receipt.get("superproject_commit") or "").lower() != commit
    ):
        return False, "release acknowledgement is stale or foreign"
    entry = _git("ls-tree", commit, "--", "ipfs_accelerate_py").split()
    if len(entry) < 3 or entry[0:2] != ["160000", "commit"]:
        return False, "release acknowledgement commit has no accelerator gitlink"
    accelerator_commit = entry[2].lower()
    if str(verification.get("accelerator_commit") or "").lower() != accelerator_commit:
        return False, "release acknowledgement accelerator commit is stale"
    try:
        accelerator_tree = _git(
            "-C", "ipfs_accelerate_py", "rev-parse", f"{accelerator_commit}^{{tree}}"
        ).lower()
    except RuntimeError:
        return False, "verified accelerator commit is unavailable locally"
    if str(verification.get("accelerator_tree") or "").lower() != accelerator_tree:
        return False, "release acknowledgement accelerator tree is stale"
    try:
        verifier_blob = _git_blob(
            commit,
            "scripts/validation/validate_accelerate_duckdb_quack_release.py",
            maximum_bytes=2 * 1024 * 1024,
        )
    except RuntimeError:
        return False, "release verifier bound by the acknowledgement is unavailable"
    if receipt["verifier_sha256"] != f"sha256:{hashlib.sha256(verifier_blob).hexdigest()}":
        return False, "release acknowledgement verifier digest is stale"
    try:
        acknowledged_at = datetime.fromisoformat(
            str(receipt["acknowledged_at"]).replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            str(verification["expires_at"]).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return False, "release acknowledgement timestamps are invalid"
    if (
        not isinstance(receipt["acknowledged_at"], str)
        or acknowledged_at.tzinfo is None
        or acknowledged_at.utcoffset() is None
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
        or acknowledged_at > expires_at
        or expires_at <= datetime.now(timezone.utc)
    ):
        return False, "release acknowledgement timestamps are unbound"
    return (
        False,
        "launch_blocker=authenticated_release_verifier_execution_receipt_missing",
    )


def _repository_binding_is_launch_compatible(
    repository_tree_id: str,
    *,
    source: Any | None = None,
) -> tuple[bool, str]:
    parts = _repository_binding_parts(repository_tree_id)
    if parts is None or not _repository_binding_is_ancestor(repository_tree_id):
        return False, "invalid or non-ancestor repository binding"
    commit, _tree = parts
    current = _git("rev-parse", "HEAD")
    selected_source = source or _source(require=False)
    if selected_source is None:
        return False, "manual-gate task-source authority is unavailable"
    manual_ok, manual_detail = _manual_gate_restart_admission(selected_source)
    if not manual_ok:
        return False, manual_detail
    if commit == current:
        return True, f"exact admitted commit and tree; {manual_detail}"
    try:
        descendants = tuple(
            item.strip().lower()
            for item in _git(
                "rev-list", "--first-parent", "--reverse", f"{commit}..{current}"
            ).splitlines()
            if item.strip()
        )
        if not descendants or descendants[-1] != current:
            return False, "first-parent descendant walk does not reach HEAD"
        authority: dict[str, Any] | None = None
        queue_rows: dict[str, dict[str, Any]] | None = None
        admitted_requests: set[str] = set()
        admitted_task_cids: set[str] = set()
        admitted_exports = 0
        admitted_merges = 0
        admitted_releases = 0
        task_cas_crash_request = ""
        merge_integrated_crash_request = ""
        previous = commit.lower()
        for descendant in descendants:
            parents = _git_commit_parents(descendant)
            if not parents or parents[0].lower() != previous:
                return False, f"first-parent gap before {descendant}"
            changed_paths = _git_changed_paths(previous, descendant)
            if len(parents) == 1 and _repository_export_commit_is_valid(
                descendant, changed_paths
            ):
                admitted_exports += 1
                previous = descendant
                continue
            if authority is None:
                selected_source = source or _source()
                authority = _repository_task_authority(selected_source)
            if len(parents) == 1:
                release_ok, release_detail = _repository_release_commit_is_valid(
                    descendant,
                    previous,
                    authority=authority,
                    admitted_task_cids=admitted_task_cids,
                )
                if not release_ok:
                    return False, f"unadmitted linear commit {descendant}: {release_detail}"
                admitted_releases += 1
                previous = descendant
                continue
            if len(parents) != 2:
                return False, f"commit {descendant} is not an exact no-ff task merge"
            if queue_rows is None:
                queue_rows = _repository_merge_queue_rows()
            tree = _git_commit_tree(descendant)
            completed, completed_detail, processing_crash = (
                _repository_completed_merge_is_valid(
                    descendant,
                    parents,
                    tree,
                    authority=authority,
                    queue_rows=queue_rows,
                    admitted_requests=admitted_requests,
                    admitted_task_cids=admitted_task_cids,
                )
            )
            if completed:
                if processing_crash:
                    if descendant != current or task_cas_crash_request:
                        return False, (
                            "post-task-CAS processing receipt is admissible only "
                            f"as the single HEAD crash tip: {descendant}"
                        )
                    task_cas_crash_request = completed_detail
                admitted_merges += 1
                previous = descendant
                continue
            pending, pending_detail = _repository_pending_tip_is_valid(
                descendant,
                parents,
                authority=authority,
                queue_rows=queue_rows,
                source=selected_source,
            )
            if pending:
                if descendant != current or merge_integrated_crash_request:
                    return False, (
                        "pre-task-CAS merge-integrated receipt is admissible only "
                        f"as the single HEAD crash tip: {descendant}"
                    )
                merge_integrated_crash_request = pending_detail
                admitted_merges += 1
                previous = descendant
                continue
            return False, (
                f"unadmitted task merge {descendant}: completed={completed_detail}; "
                f"active={pending_detail}"
            )
        if _git("rev-parse", "HEAD").lower() != current:
            return False, "repository HEAD changed during descendant admission"
        if queue_rows is not None and _repository_merge_queue_rows() != queue_rows:
            return False, "merge-queue authority changed during descendant admission"
        if authority is not None and selected_source is not None:
            final_snapshot = selected_source.snapshot()
            admitted_snapshot = authority["snapshot"]
            if any(
                getattr(final_snapshot, field) != getattr(admitted_snapshot, field)
                for field in (
                    "plan_root_cid",
                    "projection_cid",
                    "repository_tree_id",
                    "revision",
                    "event_cursor",
                )
            ):
                return False, "task-source authority changed during descendant admission"
            if (
                (task_cas_crash_request or merge_integrated_crash_request)
                and _repository_task_source_writer(selected_source)
                != authority["source_writer"]
            ):
                return False, "task-source writer changed during crash-tip admission"
        return True, (
            "controlled first-parent descendant: "
            f"receipt_merges={admitted_merges}; transport_exports={admitted_exports}; "
            f"release_pins={admitted_releases}; "
            f"task_cas_crash_tip={task_cas_crash_request or 'none'}; "
            "merge_integrated_crash_tip="
            f"{merge_integrated_crash_request or 'none'}"
        )
    except Exception as exc:
        return False, f"repository descendant evidence rejected: {type(exc).__name__}: {exc}"


def _current_formal_identity(repository_tree_id: str) -> tuple[str, str]:
    compiler_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.planning.formal_plan_compiler",
        "ipfs_accelerate_py.agent_supervisor.formal_plan_compiler",
    )
    CompilationStatus = compiler_module.CompilationStatus
    FormalPlanCompiler = compiler_module.FormalPlanCompiler

    result = FormalPlanCompiler().compile(formal_source(repository_tree_id))
    if result.status is not CompilationStatus.COMPILED or result.plan is None:
        diagnostics = "; ".join(item.message for item in result.issues[:5])
        raise RuntimeError(
            "current formal program does not compile"
            + (f": {diagnostics}" if diagnostics else "")
        )
    return str(result.plan_id), str(result.source_identity)


def _goal_cid(goal_id: str) -> str:
    for goal in GOALS:
        if goal["goal_id"] == goal_id:
            return str(goal["goal_cid"])
    raise KeyError(goal_id)


def validate_program() -> None:
    goal_ids = {str(goal["goal_id"]) for goal in GOALS}
    goal_cids = {str(goal["goal_cid"]) for goal in GOALS}
    if len(goal_ids) != len(GOALS) or len(goal_cids) != len(GOALS):
        raise ValueError("goal identities must be unique")
    for goal in GOALS:
        parent = str(goal.get("parent_goal_cid") or "")
        if parent and parent not in goal_cids:
            raise ValueError(f"goal {goal['goal_id']} has unknown parent {parent}")

    task_ids = {str(task["task_id"]) for task in TASKS}
    if len(task_ids) != len(TASKS):
        raise ValueError("task identities must be unique")
    output_owners: dict[str, list[str]] = {}
    graph: dict[str, tuple[str, ...]] = {}
    for task in TASKS:
        task_id = str(task["task_id"])
        if task["goal_id"] not in goal_ids:
            raise ValueError(f"task {task_id} has unknown goal {task['goal_id']}")
        dependencies = tuple(str(item) for item in task.get("depends_on") or ())
        unknown = set(dependencies).difference(task_ids)
        if unknown:
            raise ValueError(f"task {task_id} has unknown dependencies: {sorted(unknown)}")
        graph[task_id] = dependencies
        for effect in task.get("effects") or ():
            path = str(effect.get("path") or "")
            if path:
                output_owners.setdefault(path, []).append(task_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"task dependency cycle at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(task_ids):
        visit(task_id)

    dependency_closure: dict[str, set[str]] = {}

    def dependencies_of(task_id: str) -> set[str]:
        cached = dependency_closure.get(task_id)
        if cached is not None:
            return cached
        resolved: set[str] = set(graph[task_id])
        for dependency in graph[task_id]:
            resolved.update(dependencies_of(dependency))
        dependency_closure[task_id] = resolved
        return resolved

    for path, owners in output_owners.items():
        for index, left in enumerate(owners):
            for right in owners[index + 1 :]:
                if left not in dependencies_of(right) and right not in dependencies_of(left):
                    raise ValueError(
                        f"output {path!r} is shared by concurrently schedulable "
                        f"tasks {left} and {right}"
                    )


def formal_source(repository_tree_id: str) -> dict[str, Any]:
    validate_program()
    task_source_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.task_sources.duckdb_task_source",
        "ipfs_accelerate_py.agent_supervisor.duckdb_task_source",
    )
    proof_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts",
    )
    _task_identity_payload = task_source_module._task_identity_payload
    content_identity = proof_module.content_identity

    objectives: list[dict[str, Any]] = []
    canonical_goals: dict[str, str] = {}
    for goal in GOALS:
        record = dict(goal)
        seed_cid = str(record.pop("goal_cid"))
        parent_seed = str(record.pop("parent_goal_cid", "") or "")
        if parent_seed:
            try:
                record["parent_goal_cid"] = canonical_goals[parent_seed]
            except KeyError as exc:
                raise ValueError(
                    f"goal {record['goal_id']} parent must precede its child"
                ) from exc
        record["goal_cid"] = content_identity(record)
        canonical_goals[seed_cid] = str(record["goal_cid"])
        objectives.append(record)
    taskboard: list[dict[str, Any]] = []
    for task in TASKS:
        record = dict(task)
        seed_goal_cid = _goal_cid(str(record["goal_id"]))
        record["goal_cid"] = canonical_goals[seed_goal_cid]
        record.pop("task_cid", None)
        record["task_cid"] = content_identity(_task_identity_payload(record))
        taskboard.append(record)
    return {
        "schema": PROGRAM_SCHEMA,
        "repository_tree_id": repository_tree_id,
        "objectives": objectives,
        "taskboard": taskboard,
        "proof_policy": {
            "policy_cid": "policy:cid:duckdb-quack-program-v1",
            "minimum_code_assurance": "candidate",
            "freshness_seconds": 86400,
            "fallback_check_ids": ["fallback:focused-pytest", "fallback:integrity-check"],
        },
    }


def _accelerate_imports() -> tuple[Any, Any]:
    if not ACCELERATE_ROOT.is_dir():
        raise RuntimeError(f"initialized ipfs_accelerate_py submodule is required at {ACCELERATE_ROOT}")
    task_source_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.task_sources.duckdb_task_source",
        "ipfs_accelerate_py.agent_supervisor.duckdb_task_source",
    )
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
        _goose_meta_spark_available,
        _grok_cli_available,
    )

    return task_source_module.DuckDBTaskSource, (
        _grok_cli_available,
        _goose_meta_spark_available,
    )


def _source(*, require: bool = True) -> Any | None:
    DuckDBTaskSource, _providers = _accelerate_imports()
    if not DATABASE_PATH.is_file():
        if require:
            raise RuntimeError(f"control database does not exist: {DATABASE_PATH}")
        return None
    return DuckDBTaskSource(DATABASE_PATH)


def _retry_reset_inspection() -> dict[str, Any]:
    """Return the governed retry-reset journal launch projection."""

    try:
        module = _accelerate_module(
            "ipfs_accelerate_py.agent_supervisor.duckdb_retry_reset",
            "ipfs_accelerate_py.agent_supervisor.duckdb_retry_reset",
        )
        # The governed reset root must contain the database, every lane, and
        # the master lifecycle records.  Those are siblings below
        # ``RUNTIME_ROOT``; using ``STATE_ROOT`` would make the database and
        # master impossible to bind without an unsafe ``..`` escape and would
        # inspect the wrong journal namespace.
        incomplete = list(module.inspect_incomplete_retry_resets(RUNTIME_ROOT))
        lifecycle_root, _lock_path = _retry_lifecycle_paths()
        if lifecycle_root.exists():
            import stat

            metadata = lifecycle_root.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError("retry lifecycle journal root is unsafe")
            for path in sorted(lifecycle_root.glob("*.json")):
                payload = _read_retry_lifecycle_journal(path)
                if payload["phase"] == "completed":
                    _verify_parent_retry_reset_anchor(payload)
                else:
                    authorization = payload.get("authorization")
                    expires_at_ms = (
                        authorization.get("expires_at_ms")
                        if isinstance(authorization, Mapping)
                        else None
                    )
                    permit_expired = bool(
                        isinstance(expires_at_ms, int)
                        and not isinstance(expires_at_ms, bool)
                        and time.time_ns() // 1_000_000 >= expires_at_ms
                        and payload["phase"] in {"prepared", "draining", "drained"}
                    )
                    item = {
                        "path": str(path),
                        "phase": payload["phase"],
                        "request_id": payload["request_id"],
                        "task_cid": payload.get("task", {}).get("task_cid", ""),
                        "kind": "retry_lifecycle",
                        "permit_expired": permit_expired,
                    }
                    if permit_expired:
                        item.update(
                            {
                                "blocked_reason": "retry_permit_expired_after_lifecycle_start",
                                "recovery_action": (
                                    "master remains stopped; obtain a governed recovery "
                                    "authorization because hand-editing or bypassing the "
                                    "released reset journal is forbidden"
                                ),
                            }
                        )
                    incomplete.append(item)
    except Exception as exc:
        return {
            "ok": False,
            "incomplete": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "ok": not incomplete,
        "incomplete": [dict(item) for item in incomplete],
        "error": "",
    }


def _retry_reset_bootstrap_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Encode one retry authority record without floats or non-finite values."""

    return (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _prepare_retry_reset_bootstrap_runtime_root() -> Path:
    """Create one private runtime root before DuckDB can create its database."""

    import stat

    raw_root = RUNTIME_ROOT.absolute()
    expected_database = raw_root / "control.duckdb"
    if DATABASE_PATH.absolute() != expected_database:
        raise RuntimeError("bootstrap database path is not canonical")
    parent = raw_root.parent
    try:
        parent_metadata = parent.lstat()
    except OSError as exc:
        raise RuntimeError("bootstrap runtime parent is unavailable") from exc
    if (
        stat.S_ISLNK(parent_metadata.st_mode)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or parent.resolve() != parent
    ):
        raise RuntimeError("bootstrap runtime parent is not owner-controlled")
    try:
        os.mkdir(raw_root, mode=0o700)
    except FileExistsError:
        pass
    try:
        metadata = raw_root.lstat()
    except OSError as exc:
        raise RuntimeError("bootstrap runtime root is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or raw_root.resolve() != raw_root
    ):
        raise RuntimeError("bootstrap runtime root is not private and owner-controlled")
    return raw_root


def _assert_retry_reset_bootstrap_root(
    source: Any, *, tighten_database_mode: bool = False
) -> Path:
    """Return the canonical runtime root after strict owner/mode checks."""

    import stat

    raw_root = RUNTIME_ROOT.absolute()
    try:
        root_metadata = raw_root.lstat()
    except OSError as exc:
        raise RuntimeError("retry-reset runtime root is unavailable") from exc
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.geteuid()
        or root_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or raw_root.resolve() != raw_root
    ):
        raise RuntimeError("retry-reset runtime root is not owner-controlled")
    expected_database = raw_root / "control.duckdb"
    source_database = Path(str(source.database_path)).resolve()
    if DATABASE_PATH.absolute() != expected_database or source_database != expected_database:
        raise RuntimeError("retry-reset bootstrap database path is not canonical")
    database_metadata = expected_database.lstat()
    if (
        stat.S_ISLNK(database_metadata.st_mode)
        or not stat.S_ISREG(database_metadata.st_mode)
        or database_metadata.st_uid != os.geteuid()
        or database_metadata.st_mode & stat.S_IWOTH
    ):
        raise RuntimeError("retry-reset bootstrap database is not owner-controlled")
    if tighten_database_mode:
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(expected_database, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino)
                != (database_metadata.st_dev, database_metadata.st_ino)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or opened.st_mode & stat.S_IWOTH
            ):
                raise RuntimeError(
                    "retry-reset bootstrap database changed before mode sealing"
                )
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            sealed = os.fstat(descriptor)
            if stat.S_IMODE(sealed.st_mode) != 0o600:
                raise RuntimeError("retry-reset bootstrap database mode was not sealed")
        finally:
            os.close(descriptor)
        final = expected_database.lstat()
        if (
            (final.st_dev, final.st_ino)
            != (database_metadata.st_dev, database_metadata.st_ino)
            or stat.S_IMODE(final.st_mode) != 0o600
            or final.st_uid != os.geteuid()
        ):
            raise RuntimeError("retry-reset bootstrap database changed while sealing")
    # DuckDB inherits the process umask (commonly producing 0664).  The
    # lifecycle-lock holder narrows that freshly materialized inode to 0600
    # before publishing either authority file.
    return raw_root


def _ensure_retry_reset_bootstrap_directory(path: Path, *, parent: Path) -> None:
    """Create one fixed private directory, or verify its exact authority."""

    import stat

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o700)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError("retry-reset bootstrap directory is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise RuntimeError("retry-reset bootstrap directory is not owner-controlled")


def _retry_reset_bootstrap_existing_bytes(path: Path, *, noun: str) -> bytes | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError(f"cannot inspect {noun}") from exc
    return _strict_regular_bytes(
        path,
        noun=noun,
        required_mode=0o600,
        required_uid=os.geteuid(),
        forbidden_mode=0o077,
    )


def _durable_create_retry_reset_bootstrap_file(
    path: Path,
    expected: bytes,
    *,
    noun: str,
) -> None:
    """Create exact authority bytes once; never replace an existing inode."""

    existing = _retry_reset_bootstrap_existing_bytes(path, noun=noun)
    if existing is not None:
        if existing != expected:
            raise RuntimeError(f"existing {noun} does not match canonical bootstrap bytes")
        return

    temporary_path: Path | None = None
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(raw_temporary_path)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raced = _retry_reset_bootstrap_existing_bytes(path, noun=noun)
            if raced != expected:
                raise RuntimeError(
                    f"existing {noun} appeared with non-canonical bootstrap bytes"
                ) from exc
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    installed = _retry_reset_bootstrap_existing_bytes(path, noun=noun)
    if installed != expected:
        raise RuntimeError(f"durable {noun} verification failed")


def _retry_reset_bootstrap_authority_material(source: Any) -> dict[str, Any]:
    """Build the one exact, permanently expired bootstrap trust snapshot."""

    module = _retry_reset_module()
    authorization_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.authorization_logic",
        "ipfs_accelerate_py.agent_supervisor.authorization_logic",
    )
    control_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.control_contracts",
        "ipfs_accelerate_py.agent_supervisor.control_contracts",
    )
    snapshot = source.snapshot()
    repository_root = str(REPO_ROOT.resolve())
    runtime_root = str(RUNTIME_ROOT.absolute())
    repository_id = _repository_id()
    repository_head_tree = _git("rev-parse", "HEAD^{tree}")
    binding = {
        "program_id": PROGRAM_ID,
        "repository_root": repository_root,
        "runtime_root": runtime_root,
        "repository_id": repository_id,
        "repository_head_tree": repository_head_tree,
        "plan_root_cid": snapshot.plan_root_cid,
        "task_source_repository_tree_id": snapshot.repository_tree_id,
        "policy_path": "control/retry-reset-policy.json",
        "database_path": "control.duckdb",
        "lanes": [
            {
                "state_prefix": "dqk",
                "state_path": f"state/lane-{index}/dqk_task_state.json",
                "queue_path": f"state/lane-{index}/task_queue.json",
            }
            for index in range(2)
        ],
        "lifecycle_owner_paths": ["master/supervisor.pid"],
    }
    binding_digest = "sha256:" + _sha256_text(_canonical_json(binding))
    policy_id = "policy:ipfs-datasets-duckdb-quack-retry-bootstrap"
    policy_revision = "revision:" + binding_digest
    effect_id = "effect:retry-reset-bootstrap-authority:" + binding_digest
    caller = "owner:ipfs-datasets-duckdb-quack-bootstrap"
    lease_id = "lease:ipfs-datasets-duckdb-quack-bootstrap"
    decision = control_module.AuthorizationDecision(
        verdict="permit",
        operation="retry",
        granted_authority="mutation",
        repository_root=repository_root,
        state_root=runtime_root,
        repository_id=repository_id,
        tree_id=repository_head_tree,
        objective_id=ROOT_GOAL_CID,
        objective_revision=snapshot.plan_root_cid,
        policy_id=policy_id,
        policy_revision=policy_revision,
        caller=caller,
        lease_id=lease_id,
        fencing_epoch=1,
        authorized_effect_ids=(effect_id,),
        grant_ids=(module.RETRY_RESET_GRANT,),
        evaluated_at_ms=0,
        expires_at_ms=1,
    )
    policy = authorization_module.ControlMutationPolicy(
        policy_id=policy_id,
        policy_revision=policy_revision,
        permits=(decision,),
        current_tree_ids={repository_id: repository_head_tree},
        current_objective_revisions={ROOT_GOAL_CID: snapshot.plan_root_cid},
        active_lease_fences={lease_id: 1},
    )
    policy_bytes = _retry_reset_bootstrap_json_bytes(module._policy_payload(policy))
    policy_digest = "sha256:" + hashlib.sha256(policy_bytes).hexdigest()
    owner = module.RetryResetOwnerConfig(
        repository_root=repository_root,
        repository_id=repository_id,
        database_path="control.duckdb",
        task_source_repository_tree_id=snapshot.repository_tree_id,
        policy_path="control/retry-reset-policy.json",
        policy_digest=policy_digest,
        lanes=tuple(
            module.LaneBinding(
                item["state_prefix"], item["state_path"], item["queue_path"]
            )
            for item in binding["lanes"]
        ),
        lifecycle_owner_paths=("master/supervisor.pid",),
    )
    owner_bytes = _retry_reset_bootstrap_json_bytes(owner.to_dict())
    return {
        "module": module,
        "policy": policy,
        "owner": owner,
        "policy_bytes": policy_bytes,
        "owner_bytes": owner_bytes,
        "policy_digest": policy_digest,
        "owner_digest": "sha256:" + hashlib.sha256(owner_bytes).hexdigest(),
        "binding_digest": binding_digest,
    }


def _install_retry_reset_bootstrap_authority(source: Any) -> dict[str, str]:
    """Install the canonical inert retry authority under its released lock."""

    runtime_root = _assert_retry_reset_bootstrap_root(source)
    with _retry_lifecycle_lock_context():
        runtime_root = _assert_retry_reset_bootstrap_root(source)
        material = _retry_reset_bootstrap_authority_material(source)
        module = material["module"]
        owner_path = runtime_root / module.RETRY_RESET_OWNER_FILE
        policy_path = runtime_root / "control/retry-reset-policy.json"
        existing_owner = _retry_reset_bootstrap_existing_bytes(
            owner_path, noun="retry-reset owner configuration"
        )
        try:
            policy_parent_metadata = policy_path.parent.lstat()
        except FileNotFoundError:
            existing_policy = None
        else:
            import stat

            if (
                stat.S_ISLNK(policy_parent_metadata.st_mode)
                or not stat.S_ISDIR(policy_parent_metadata.st_mode)
            ):
                raise RuntimeError("retry-reset bootstrap policy parent is unsafe")
            existing_policy = _retry_reset_bootstrap_existing_bytes(
                policy_path, noun="retry-reset bootstrap policy"
            )
        if existing_owner is not None and existing_policy is None:
            raise RuntimeError(
                "retry-reset owner exists without its policy; refusing reconstruction"
            )
        if existing_owner is not None and existing_owner != material["owner_bytes"]:
            raise RuntimeError("existing retry-reset owner does not match bootstrap authority")
        if existing_policy is not None and existing_policy != material["policy_bytes"]:
            raise RuntimeError("existing retry-reset policy does not match bootstrap authority")

        runtime_root = _assert_retry_reset_bootstrap_root(
            source, tighten_database_mode=True
        )
        _ensure_retry_reset_bootstrap_directory(
            policy_path.parent, parent=runtime_root
        )
        # This order is the supported crash boundary: a matching orphan policy
        # is replayable, while an owner can never point at an absent policy.
        _durable_create_retry_reset_bootstrap_file(
            policy_path,
            material["policy_bytes"],
            noun="retry-reset bootstrap policy",
        )
        _durable_create_retry_reset_bootstrap_file(
            owner_path,
            material["owner_bytes"],
            noun="retry-reset owner configuration",
        )

        owner = module._load_owner_config(runtime_root)
        loaded_policy = module._load_policy(
            policy_path, expected_digest=owner.policy_digest
        )
        if owner != material["owner"] or loaded_policy != material["policy"]:
            raise RuntimeError("installed retry-reset authority did not round-trip exactly")
        return {
            "owner_path": str(owner_path),
            "owner_digest": str(material["owner_digest"]),
            "policy_path": str(policy_path),
            "policy_digest": str(material["policy_digest"]),
            "binding_digest": str(material["binding_digest"]),
        }


def _all_rows(source: Any, table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = 0
    page_size = 1000
    while True:
        page = tuple(source.query(table, cursor=cursor, limit=page_size))
        rows.extend(dict(item) for item in page)
        if len(page) < page_size:
            return rows
        cursor += len(page)


def _consistent_rows(
    source: Any,
    tables: Iterable[str],
) -> tuple[Any, dict[str, list[dict[str, Any]]], dict[str, int]]:
    reader = getattr(source, "read_consistent_projection", None)
    if not callable(reader):
        raise RuntimeError(
            "the pinned DuckDB task source must support read_consistent_projection"
        )
    projection = reader(tuple(tables))
    rows = {
        str(table): [dict(item) for item in table_rows]
        for table, table_rows in projection.tables.items()
    }
    row_counts = {
        str(table): int(count) for table, count in projection.row_counts.items()
    }
    for table, table_rows in rows.items():
        if row_counts.get(table) != len(table_rows):
            raise RuntimeError(f"consistent projection row count mismatch for {table}")
    return projection.snapshot, rows, row_counts


def _decode_body(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("body_json")
    decoded = json.loads(str(value)) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("task/goal body is not an object")
    return decoded


def database_projection(source: Any) -> dict[str, Any]:
    snapshot, tables, row_counts = _consistent_rows(source, EXPORT_TABLES)
    payload = {
        "schema": "ipfs_datasets_py/duckdb-quack-plan-export@1",
        "program_id": PROGRAM_ID,
        "source_schema": snapshot.source_schema,
        "schema_version": snapshot.schema_version,
        "plan_root_cid": snapshot.plan_root_cid,
        "projection_cid": snapshot.projection_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "revision": snapshot.revision,
        "event_cursor": snapshot.event_cursor,
        "row_counts": row_counts,
        "tables": tables,
    }
    payload["export_digest"] = f"sha256:{_sha256_text(_canonical_json(payload))}"
    return payload


def _latest_status_receipt(
    events: Sequence[Mapping[str, Any]],
    *,
    task_cid: str,
    status: str,
) -> dict[str, Any] | None:
    for row in reversed(events):
        if str(row.get("task_cid") or "") != task_cid:
            continue
        try:
            body = json.loads(str(row.get("body_json") or ""))
        except json.JSONDecodeError:
            continue
        if not isinstance(body, dict) or body.get("status") != status:
            continue
        receipt = body.get("receipt")
        if isinstance(receipt, dict):
            return receipt
    return None


def _bootstrap_completion_evidence_from_tables(
    source: Any,
    snapshot: Any,
    tasks: Sequence[Mapping[str, Any]],
    task_events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    formal_contracts = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts",
    )
    bootstrap_rows = [
        row
        for row in tasks
        if str(row.get("task_alias") or "") == BOOTSTRAP_TASK_ID
    ]
    if len(bootstrap_rows) != 1:
        raise RuntimeError(f"expected exactly one {BOOTSTRAP_TASK_ID} task row")
    task = bootstrap_rows[0]
    task_cid = str(task.get("task_cid") or "")
    task_revision = task.get("revision")
    if (
        isinstance(task_revision, bool)
        or not isinstance(task_revision, int)
        or task_revision < 2
        or str(task.get("status") or "") != "completed"
    ):
        raise RuntimeError("bootstrap completion task row is not current")
    candidates: list[dict[str, Any]] = []
    for row in task_events:
        if (
            str(row.get("task_cid") or "") != task_cid
            or str(row.get("event_type") or "") != "status_changed"
        ):
            continue
        body_json = row.get("body_json")
        body = _strict_json_object(
            body_json,
            noun=f"bootstrap event {row.get('event_cid') or '?'}",
        )
        if body.get("status") != "completed" or _safe_int(
            body.get("task_revision"), 0
        ) != task_revision:
            continue
        canonical_body_bytes = formal_contracts.canonical_json_bytes(body)
        if body_json.encode("utf-8") != canonical_body_bytes:
            raise RuntimeError("bootstrap completion event bytes are noncanonical")
        recomputed_event_cid = str(formal_contracts.content_identity(body))
        if str(row.get("event_cid") or "") != recomputed_event_cid:
            raise RuntimeError("bootstrap completion event CID is forged")
        candidates.append(
            {
                "event_cid": recomputed_event_cid,
                "sequence": row.get("sequence"),
                "revision": row.get("revision"),
                "task_cid": task_cid,
                "event_type": "status_changed",
                "body": body,
            }
        )
    if len(candidates) != 1:
        raise RuntimeError(
            "bootstrap completion event is missing, duplicated, or stale"
        )
    module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon",
        "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon",
    )
    evidence = module.duckdb_bootstrap_completion_evidence(
        task_id=BOOTSTRAP_TASK_ID,
        task_cid=task_cid,
        task_status="completed",
        task_revision=task_revision,
        event=candidates[0],
        task_source_identity=_repository_task_source_identity(source, snapshot),
    )
    if set(evidence) != {
        "schema",
        "task_id",
        "task_cid",
        "task_source_identity_id",
        "event_cid",
        "task_source_receipt_id",
        "evidence_id",
    }:
        raise RuntimeError("bootstrap completion evidence shape is unsupported")
    receipt = candidates[0]["body"].get("receipt")
    if not isinstance(receipt, Mapping):
        raise RuntimeError("bootstrap completion receipt is not an object")
    return evidence, dict(receipt)


def _bootstrap_bridge_receipt_contract(
    source: Any,
    snapshot: Any,
    tasks: Sequence[Mapping[str, Any]],
    task_events: Sequence[Mapping[str, Any]],
) -> tuple[bool, str, str]:
    """Authenticate the sole completion that launch may explicitly trust."""

    bootstrap_rows = [
        row
        for row in tasks
        if str(row.get("task_alias") or "") == BOOTSTRAP_TASK_ID
    ]
    if len(bootstrap_rows) != 1:
        return False, f"expected exactly one {BOOTSTRAP_TASK_ID} task row", ""
    bootstrap = bootstrap_rows[0]
    task_cid = str(bootstrap.get("task_cid") or "")
    status = str(bootstrap.get("status") or "")
    try:
        completion_evidence, receipt = _bootstrap_completion_evidence_from_tables(
            source,
            snapshot,
            tasks,
            task_events,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        return False, f"{BOOTSTRAP_TASK_ID} completion evidence invalid: {exc}", ""
    detail_prefix = (
        f"{BOOTSTRAP_TASK_ID} status={status}; "
        f"typed_receipt={bool(receipt)}; "
        f"submodule_commit={str((receipt or {}).get('submodule_commit') or 'missing')}"
    )
    validation = (
        receipt.get("validation") if isinstance(receipt, Mapping) else None
    )
    validator_receipt = (
        validation.get("validator_receipt")
        if isinstance(validation, Mapping)
        else None
    )
    validator_valid, validator_detail = _validate_bootstrap_validator_receipt(
        validator_receipt,
        require_current_checkout=False,
    )
    submodule_commit = str((receipt or {}).get("submodule_commit") or "")
    submodule_tree = str((receipt or {}).get("submodule_tree") or "")
    superproject_commit = str(
        (receipt or {}).get("superproject_commit") or ""
    )
    superproject_tree = str((receipt or {}).get("superproject_tree") or "")
    valid = bool(
        status == "completed"
        and receipt
        and receipt.get("schema")
        == "ipfs_datasets_py/duckdb-quack-bootstrap-receipt@1"
        and receipt.get("kind") == "bootstrap_implementation_receipt"
        and receipt.get("required_bridge_commit")
        == REQUIRED_ACCELERATE_BRIDGE_COMMIT
        and receipt.get("task_cid") == task_cid
        and receipt.get("task_source_identity_id")
        == _repository_task_source_identity(source, snapshot)["identity_id"]
        and receipt.get("plan_root_cid") == snapshot.plan_root_cid
        and receipt.get("repository_tree_id") == snapshot.repository_tree_id
        and isinstance(validation, Mapping)
        and validation.get("argv") == list(_bootstrap_bridge_validation_argv())
        and _safe_int(validation.get("exit_status"), -1) == 0
        and validator_valid
        and validation.get("validator_receipt_id")
        == validator_receipt.get("receipt_id")
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(validation.get("output_sha256") or ""),
        )
        is not None
        and submodule_commit
        and submodule_tree
        and superproject_commit
        and superproject_tree
    )
    if not valid:
        suffix = "" if validator_valid else f"; validator={validator_detail}"
        return False, detail_prefix + suffix, ""
    ancestry_checks = (
        (submodule_commit, "HEAD", ACCELERATE_ROOT),
        (superproject_commit, "HEAD", REPO_ROOT),
        (
            REQUIRED_ACCELERATE_BRIDGE_COMMIT,
            submodule_commit,
            ACCELERATE_ROOT,
        ),
    )
    for ancestor, descendant, cwd in ancestry_checks:
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        ).returncode != 0:
            return False, detail_prefix + "; receipt Git ancestry is stale", ""
    try:
        tree_valid = bool(
            _git(
                "-C",
                "ipfs_accelerate_py",
                "rev-parse",
                f"{submodule_commit}^{{tree}}",
            )
            == submodule_tree
            and _git("rev-parse", f"{superproject_commit}^{{tree}}")
            == superproject_tree
        )
    except RuntimeError as exc:
        return (
            False,
            detail_prefix + f"; receipt tree lookup failed: {exc}",
            "",
        )
    if not tree_valid:
        return False, detail_prefix + "; receipt Git tree identity mismatch", ""
    evidence_id = str(completion_evidence["evidence_id"])
    return True, detail_prefix + f"; evidence_id={evidence_id}", evidence_id


def render_markdown(source: Any) -> str:
    projection = database_projection(source)
    goals = projection["tables"]["goals"]
    tasks = projection["tables"]["tasks"]
    dependencies = projection["tables"]["task_dependencies"]
    goal_by_cid = {str(row["goal_cid"]): _decode_body(row) for row in goals}
    root = next(
        body for body in goal_by_cid.values() if body.get("goal_id") == ROOT_GOAL_ID
    )
    architecture = root["architecture"]
    dependency_alias = {
        str(row["task_cid"]): str(row["task_alias"]) for row in tasks
    }
    dependencies_by_task: dict[str, list[str]] = {}
    for row in dependencies:
        dependencies_by_task.setdefault(str(row["task_cid"]), []).append(
            dependency_alias[str(row["dependency_task_cid"])]
        )
    task_records = []
    for row in tasks:
        body = _decode_body(row)
        body["status"] = str(row["status"])
        body["revision"] = int(row["revision"])
        body["depends_on"] = sorted(dependencies_by_task.get(str(row["task_cid"]), []))
        task_records.append(body)
    task_records.sort(key=lambda item: item["task_id"])
    status_counts = Counter(str(item["status"]) for item in task_records)

    lines = [
        "# IPFS Datasets DuckDB + Quack + DuckLake Data-Platform Improvement Plan",
        "",
        "> Generated projection only. The DuckDB task source is authoritative; do not edit this file to steer work.",
        "",
        f"- Program: `{PROGRAM_ID}`",
        f"- Plan root: `{projection['plan_root_cid']}`",
        f"- Repository tree: `{projection['repository_tree_id']}`",
        f"- Database revision: `{projection['revision']}`",
        f"- Projection CID: `{projection['projection_cid']}`",
        f"- Export payload digest: `{projection['export_digest']}`",
        f"- Goals: {len(goals)}; tasks: {len(tasks)}; statuses: "
        + ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items())),
        "",
        "## Decision",
        "",
        str(architecture["decision"]),
        "",
        "Quack is deliberately only the remote SQL transport. Agent scheduling, atomic claims, leases, heartbeats, retries, idempotency, dependency resolution, dead letters, and watchdog recovery remain explicit supervisor responsibilities.",
        "",
        "## Target topology",
        "",
        "```mermaid",
        "flowchart LR",
        "    A[Untrusted agents and remote services] -->|allowlisted SQL RPC| Q[Quack gateways]",
        "    Q --> U[(Physically separate sanitized publication DuckDB)]",
        "    B[Trusted query broker and projection workers] --> C[(Control DuckDB)]",
        "    B --> G[(Graph + vector authority catalog)]",
        "    B --> P[(Proof authority catalog)]",
        "    B --> S[(AST authority catalog)]",
        "    B --> W[(Wallet authority catalog)]",
        "    B --> D[Distributed DuckDB lake clients]",
        "    B -->|signed typed operations; tokens retained| M[Internal Quack endpoint registry]",
        "    M --> Q1[DuckDB + Quack owner: shard A]",
        "    M --> Q2[DuckDB + Quack owner: shard B..N]",
        "    Q1 -->|sole client| L1[(DuckLake catalog A: DuckDB file)]",
        "    Q2 -->|sole client per shard| L2[(DuckLake catalogs B..N: DuckDB files)]",
        "    D -->|authenticated remote attachments| Q1",
        "    D -->|authenticated remote attachments| Q2",
        "    Q1 --> O[(Owned Parquet in lifecycle-managed object / filesystem storage)]",
        "    Q2 --> O",
        "    G -->|fenced immutable projection| D",
        "    P -->|fenced immutable projection| D",
        "    S -->|fenced immutable projection| D",
        "    W -->|redacted public projection| D",
        "    B -->|fenced allowlisted snapshot copy| U",
        "    D -->|fenced sanitized snapshot copy| U",
        "    G --> I[(IPLD / CAR / Parquet)]",
        "    P --> I",
        "    S --> I",
        "    W --> E[(Encrypted/raw object store)]",
        "    C --> X[Deterministic MD/JSON exports]",
        "```",
        "",
        "The small control writer is isolated from analytical scans. Only the trusted in-process broker attaches identified, mostly read-only authority catalogs. The distributed DuckLake catalog plane is built from independently fenced DuckDB + Quack owners: one owner process is the sole client of each DuckDB-backed DuckLake catalog file, while remote DuckDB workers connect through Quack and never open catalog files directly. The broker retains every Quack token and short-lived object-storage capability, and each endpoint accepts only signed typed operations. Horizontal scale comes from multiple catalog shards; bounded federation combines explicit per-shard snapshot receipts rather than pretending one DuckDB file is a replicated multi-writer database. Workers copy-publish allowlisted results into the separate public Quack database, whose process can never open DuckLake metadata or authority catalogs. Cross-file and cross-catalog changes use outboxes, immutable receipts, and idempotent reconciliation instead of assuming atomicity.",
        "",
        "## Design principles",
        "",
    ]
    lines.extend(f"- {item}" for item in architecture["principles"])
    lines.extend(["", "## Catalog and table families", ""])
    lines.extend(["| Catalog | Principal tables |", "|---|---|"])
    for catalog, tables_for_catalog in architecture["catalogs"].items():
        lines.append(f"| `{catalog}` | " + ", ".join(f"`{item}`" for item in tables_for_catalog) + " |")
    lines.extend(["", "## Quack deployment constraints", ""])
    lines.extend(f"- {item}" for item in architecture["quack_constraints"])
    lines.extend(["", "## DuckLake deployment constraints", ""])
    lines.extend(f"- {item}" for item in architecture["ducklake_constraints"])
    lines.extend(["", "## Rollout and authority transition", ""])
    lines.extend(f"{index}. {item}" for index, item in enumerate(architecture["rollout"], 1))
    lines.extend(["", "## Risks and mitigations", "", "| Risk | Mitigation |", "|---|---|"])
    for risk, mitigation in architecture["risks"].items():
        lines.append(f"| `{risk}` | {mitigation} |")
    lines.extend(["", "## Success metrics", ""])
    lines.extend(f"- {item}" for item in architecture["success_metrics"])
    lines.extend(["", "## Goals and subgoals", ""])
    for row in sorted(goals, key=lambda item: int(item["ordinal"])):
        body = _decode_body(row)
        parent = str(row["parent_goal_cid"] or "")
        suffix = f" (parent `{parent}`)" if parent else ""
        lines.extend([f"### {body['goal_id']}: {row['title']}{suffix}", ""])
        if body.get("objective"):
            lines.extend([str(body["objective"]), ""])
        for criterion in body.get("acceptance_criteria") or ():
            lines.append(f"- {criterion}")
        lines.append("")
    lines.extend(["## Execution task graph", ""])
    for task in task_records:
        outputs = [
            str(item["path"])
            for item in task.get("effects") or ()
            if str(item.get("path") or "")
        ]
        lines.extend(
            [
                f"### {task['task_id']}: {task['title']}",
                "",
                f"- Status/revision: `{task['status']}` / `{task['revision']}`",
                f"- Goal: `{task['goal_id']}`; priority: `{task['priority']}`; track: `{task['track']}`",
                "- Depends on: " + (", ".join(f"`{item}`" for item in task["depends_on"]) or "none"),
                "- Outputs: "
                + (", ".join(f"`{item}`" for item in outputs) or "none"),
                "",
                str(task["objective"]),
                "",
                "Acceptance:",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in task.get("acceptance_criteria") or ())
        lines.extend(["", "Validation:", ""])
        lines.extend(f"- `{item}`" for item in task.get("validation_commands") or ())
        lines.append("")
    lines.extend(
        [
            "## Source references",
            "",
            "- DuckDB Quack: https://duckdb.org/quack/",
            "- Quack overview: https://duckdb.org/docs/current/quack/overview",
            "- Quack reference and authentication/authorization hooks: https://duckdb.org/docs/current/quack/reference",
            "- Quack security: https://duckdb.org/docs/current/quack/security",
            "- DuckDB concurrency: https://duckdb.org/docs/current/connect/concurrency",
            "- DuckDB environment guidance for local database storage: https://duckdb.org/docs/current/guides/performance/environment",
            "- DuckDB VSS: https://duckdb.org/docs/lts/core_extensions/vss",
            "- DuckDB 1.5 DuckLake extension: https://duckdb.org/docs/current/core_extensions/ducklake",
            "- DuckDB 1.4 LTS DuckLake compatibility reference: https://duckdb.org/docs/lts/core_extensions/ducklake",
            "- DuckLake stable documentation: https://ducklake.select/docs/stable/",
            "- DuckLake v1.0 specification: https://ducklake.select/docs/stable/specification/introduction",
            "- DuckLake catalog selection: https://ducklake.select/docs/stable/duckdb/usage/choosing_a_catalog_database",
            "- DuckLake adding existing Parquet files: https://ducklake.select/docs/stable/duckdb/metadata/adding_files",
            "- DuckLake schema evolution: https://ducklake.select/docs/stable/duckdb/usage/schema_evolution",
            "- DuckLake access control: https://ducklake.select/docs/stable/duckdb/guides/access_control",
            "- DuckLake backup and recovery: https://ducklake.select/docs/stable/duckdb/guides/backups_and_recovery",
            "- DuckLake maintenance: https://ducklake.select/docs/stable/duckdb/maintenance/recommended_maintenance",
            "",
        ]
    )
    body = "\n".join(lines)
    return body + f"\n<!-- rendered-body-sha256: {_sha256_text(body)} -->\n"


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for item in value.split("."):
        digits = "".join(character for character in item if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _pid_exists(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _process_birth_identity(pid: int) -> dict[str, Any] | None:
    if not _pid_exists(pid):
        return None
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        stat_tail = stat_text.rsplit(") ", 1)[1].split()
        start_ticks = int(stat_tail[19])
        command_bytes = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, IndexError, ValueError):
        return None
    if not boot_id or not command_bytes:
        return None
    argv = tuple(
        item.decode("utf-8", errors="replace")
        for item in command_bytes.split(b"\0")
        if item
    )
    return {
        "pid": pid,
        "boot_id": boot_id,
        "start_ticks": start_ticks,
        "cmdline_sha256": f"sha256:{hashlib.sha256(command_bytes).hexdigest()}",
        "argv": argv,
    }


def _task_validation_toolchain_material() -> dict[str, str]:
    return {
        "schema": "ipfs_datasets_py/duckdb-quack-task-validation-toolchain@1",
        "python_path": str(TASK_VALIDATION_PYTHON),
        "python_sha256": TASK_VALIDATION_PYTHON_SHA256,
        "dispatch_source_sha256": TASK_VALIDATION_DISPATCH_SHA256,
        "validator_receipt_id": TASK_VALIDATOR_RECEIPT_ID,
        "cache_receipt_id": TASK_VALIDATOR_CACHE_RECEIPT_ID,
        "validator_policy_sha256": BOOTSTRAP_VALIDATOR_SHA256,
        "validator_lock_sha256": BOOTSTRAP_VALIDATOR_REQUIREMENTS_SHA256,
    }


def _task_validation_toolchain_id() -> str:
    return (
        "sha256:"
        + _sha256_text(_canonical_json(_task_validation_toolchain_material()))
    )


def _task_validation_environment() -> dict[str, str]:
    return {
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON": str(TASK_VALIDATION_PYTHON),
        "IPFS_DATASETS_DQK_VALIDATION_TOOLCHAIN_ID": (
            _task_validation_toolchain_id()
        ),
    }


def _sealed_python_environment() -> dict[str, str]:
    return {
        **_ACCELERATE_IMPORT_ENVIRONMENT,
        **_task_validation_environment(),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(ACCELERATE_ROOT.resolve()),
        "PYTHONSAFEPATH": "1",
    }


def _runtime_python_environment_key(key: str) -> bool:
    return bool(
        key.startswith("PYTHON")
        or key.startswith("LD_")
        or key.startswith("IPFS_ACCELERATE_AGENT_VALIDATION_")
        or key.startswith("IPFS_DATASETS_DQK_VALIDATION_")
        or key in _ACCELERATE_IMPORT_ENVIRONMENT
    )


def _runtime_python_environment(
    environment: Mapping[str, str],
) -> dict[str, str]:
    return {
        key: value
        for key, value in environment.items()
        if _runtime_python_environment_key(key)
    }


def _process_python_environment(pid: int) -> dict[str, str] | None:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key_bytes, value_bytes = item.split(b"=", 1)
        key = key_bytes.decode("utf-8", errors="replace")
        if _runtime_python_environment_key(key):
            result[key] = value_bytes.decode("utf-8", errors="replace")
    return result


def _scrubbed_sealed_process_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environment is None else environment)
    for key in tuple(result):
        if _runtime_python_environment_key(key):
            result.pop(key)
    result.update(_sealed_python_environment())
    return result


def _expanded_sealed_python_argv(
    logical_argv: Sequence[str],
) -> tuple[str, ...]:
    """Expand one exact logical wrapper argv to its Linux process argv."""

    logical = tuple(str(item) for item in logical_argv)
    if not logical or logical[0] != str(SEALED_PYTHON_LAUNCHER):
        raise ValueError("logical argv does not name the exact sealed launcher")
    return (
        str(_trusted_base_python_path()),
        "-I",
        "-B",
        "-S",
        "-c",
        _sealed_python_dispatch_source(_sealed_python_paths()),
        *logical[1:],
    )


def _logical_sealed_python_argv(
    process_argv: Sequence[str],
) -> tuple[str, ...] | None:
    """Recover the trusted logical wrapper argv from exact expanded bytes."""

    actual = tuple(str(item) for item in process_argv)
    try:
        expansion_prefix = _expanded_sealed_python_argv(
            (str(SEALED_PYTHON_LAUNCHER),)
        )
    except (OSError, RuntimeError, ValueError):
        return None
    if actual[: len(expansion_prefix)] != expansion_prefix:
        return None
    return (str(SEALED_PYTHON_LAUNCHER), *actual[len(expansion_prefix) :])


def _process_identity_matches_sealed_command(
    identity: Mapping[str, Any] | None,
    logical_command: Sequence[str],
) -> bool:
    if not identity:
        return False
    return _logical_sealed_python_argv(
        tuple(str(item) for item in identity.get("argv") or ())
    ) == tuple(str(item) for item in logical_command)


def _option_value(argv: Sequence[str], option: str) -> str:
    for index, item in enumerate(argv):
        if item == option and index + 1 < len(argv):
            return str(argv[index + 1])
        if item.startswith(option + "="):
            return item.split("=", 1)[1]
    return ""


def _master_execution_slice(argv: Sequence[str]) -> tuple[str, ...]:
    """Extract the exact runner-to-supervisor execution allowlist."""

    marker = "--common-arg=--execution-slice-task-id"
    prefix = "--common-arg="
    aliases: list[str] = []
    for index, item in enumerate(argv):
        if item != marker:
            continue
        if index + 1 >= len(argv) or not str(argv[index + 1]).startswith(prefix):
            raise RuntimeError("master execution-slice option has no value")
        alias = str(argv[index + 1])[len(prefix) :].strip()
        if not alias or alias.startswith("--"):
            raise RuntimeError("master execution-slice value is invalid")
        aliases.append(alias)
    if not aliases or len(aliases) != len(set(aliases)):
        raise RuntimeError("master execution slice is empty or duplicated")
    return tuple(aliases)


def _master_single_common_arg_value(
    argv: Sequence[str],
    option: str,
) -> str:
    """Extract one runner-forwarded value while rejecting duplicate authority."""

    marker = f"--common-arg={option}"
    prefix = "--common-arg="
    if any(str(item).startswith(marker + "=") for item in argv):
        raise RuntimeError(f"master common option {option} uses an unsupported form")
    indexes = [index for index, item in enumerate(argv) if item == marker]
    if not indexes:
        return ""
    if len(indexes) != 1 or indexes[0] + 1 >= len(argv):
        raise RuntimeError(f"master common option {option} is duplicated or incomplete")
    raw = str(argv[indexes[0] + 1])
    if not raw.startswith(prefix):
        raise RuntimeError(f"master common option {option} has no forwarded value")
    value = raw[len(prefix) :].strip()
    if not value or value.startswith("--"):
        raise RuntimeError(f"master common option {option} value is invalid")
    return value


def _execution_slice_digest(
    *,
    plan_root_cid: str,
    repository_tree_id: str,
    task_aliases: Sequence[str],
    held_task_aliases: Sequence[str] = (),
    held_set_sha256: str = "",
) -> str:
    payload = {
        "schema": "ipfs_datasets_py/duckdb-execution-slice@2",
        "plan_root_cid": str(plan_root_cid),
        "repository_tree_id": str(repository_tree_id),
        "task_aliases": list(task_aliases),
        "held_task_aliases": list(held_task_aliases),
        "held_set_sha256": str(held_set_sha256),
    }
    return f"sha256:{_sha256_text(_canonical_json(payload))}"


def _actual_master_command_matches(identity: Mapping[str, Any]) -> bool:
    """Fail closed unless *identity* has this program's canonical master argv.

    The duration and detach mode are launch-time choices, so reconstruct the
    canonical command with the observed values instead of guessing which mode
    launched the process.  The process-birth receipt subsequently binds their
    exact bytes through ``cmdline_sha256``.
    """

    argv = _logical_sealed_python_argv(
        tuple(str(item) for item in identity.get("argv") or ())
    )
    if argv is None:
        return False
    duration_indexes = tuple(
        index for index, item in enumerate(argv) if item == "--duration-seconds"
    )
    if len(duration_indexes) != 1 or duration_indexes[0] + 1 >= len(argv):
        return False
    duration_index = duration_indexes[0]
    duration_text = argv[duration_index + 1]
    try:
        duration_seconds = float(duration_text)
        lanes = int(
            _option_value(argv, "--implementation-supervisor-lanes-per-track")
        )
    except (TypeError, ValueError):
        return False
    if not duration_seconds > 0 or not 1 <= lanes <= MAX_IMPLEMENTATION_LANES:
        return False
    detach_count = argv.count("--detach")
    if detach_count > 1:
        return False
    stamp = _option_value(argv, "--stamp")
    match = re.fullmatch(r"dqk-[0-9a-z]+-([0-9a-f]{32})", stamp)
    if match is None:
        return False
    launch_token = match.group(1)
    try:
        expected = tuple(
            supervisor_command(
                lanes=lanes,
                duration_seconds=duration_seconds,
                detach=detach_count == 1,
                launch_token=launch_token,
            )
        )
    except Exception:
        # A missing, unreadable, or changing task source cannot authorize a PID.
        return False

    # ``supervisor_command`` canonicalizes a float (for example ``3600.0``),
    # while direct callers may have produced the equivalent ``3600``.  Duration
    # is deliberately variable but must remain in its one canonical argv slot.
    expected_duration_indexes = tuple(
        index for index, item in enumerate(expected) if item == "--duration-seconds"
    )
    if len(expected_duration_indexes) != 1:
        return False
    normalized_actual = list(argv)
    normalized_expected = list(expected)
    normalized_actual[duration_index + 1] = "<bound-duration>"
    normalized_expected[expected_duration_indexes[0] + 1] = "<bound-duration>"
    return tuple(normalized_actual) == tuple(normalized_expected)


def _read_master_identity() -> dict[str, Any] | None:
    try:
        payload = json.loads(MASTER_IDENTITY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _master_process_status(
    pid: int | None,
    *,
    expected_plan_root: str = "",
    expected_repository_root: str = "",
) -> tuple[bool, str]:
    if not _pid_exists(pid):
        return False, "pid_not_live"
    assert pid is not None
    actual = _process_birth_identity(pid)
    if actual is None:
        return False, "process_identity_unreadable"
    if not _actual_master_command_matches(actual):
        return False, "pid_command_does_not_match_program_master"
    logical_argv = _logical_sealed_python_argv(
        tuple(str(item) for item in actual.get("argv") or ())
    )
    if logical_argv is None:
        return False, "pid_command_does_not_match_program_master"
    try:
        actual_bootstrap_evidence_id = _master_single_common_arg_value(
            logical_argv,
            "--duckdb-bootstrap-completion-evidence-id",
        )
    except RuntimeError:
        return False, "master_bootstrap_completion_evidence_is_duplicated"
    python_environment = _process_python_environment(pid)
    if python_environment != _sealed_python_environment():
        return False, "master_python_environment_is_not_sealed"
    stored = _read_master_identity()
    if stored is None:
        return False, "missing_master_identity"
    required_equal = (
        "pid",
        "boot_id",
        "start_ticks",
        "cmdline_sha256",
    )
    if any(stored.get(key) != actual.get(key) for key in required_equal):
        return False, "master_process_birth_identity_mismatch"
    if stored.get("python_environment_sha256") != (
        f"sha256:{_sha256_text(_canonical_json(python_environment))}"
    ):
        return False, "master_python_environment_receipt_mismatch"
    expected_bindings = {
        "schema": "ipfs_datasets_py/duckdb-quack-master-identity@3",
        "program_id": PROGRAM_ID,
        "repository_root": str(REPO_ROOT),
        "master_root": str(MASTER_ROOT),
        "master_pid_path": str(MASTER_PID),
    }
    if any(stored.get(key) != value for key, value in expected_bindings.items()):
        return False, "stored_master_program_binding_mismatch"
    if expected_plan_root and stored.get("plan_root_cid") != expected_plan_root:
        return False, "stored_master_plan_root_mismatch"
    if (
        expected_repository_root
        and stored.get("repository_tree_id") != expected_repository_root
    ):
        return False, "stored_master_repository_root_mismatch"
    actual_lane_count = _safe_int(
        _option_value(
            logical_argv,
            "--implementation-supervisor-lanes-per-track",
        )
    )
    if _safe_int(stored.get("lane_count")) != actual_lane_count or actual_lane_count < 1:
        return False, "stored_master_lane_count_mismatch"
    try:
        actual_slice = _master_execution_slice(logical_argv)
        selected_source = _source(require=False)
        if selected_source is None:
            raise RuntimeError("manual-gate authority source is unavailable")
        held_snapshot, hold_projection = _manual_gate_hold_projection(selected_source)
        (
            _launch_snapshot,
            _launch_slice,
            _launch_slice_digest,
            expected_bootstrap_evidence_id,
        ) = _task_source_launch_contract(selected_source)
        if (
            held_snapshot.plan_root_cid != str(stored.get("plan_root_cid") or "")
            or held_snapshot.repository_tree_id
            != str(stored.get("repository_tree_id") or "")
        ):
            raise RuntimeError("manual-gate held set is from another generation")
        actual_slice_digest = _execution_slice_digest(
            plan_root_cid=str(stored.get("plan_root_cid") or ""),
            repository_tree_id=str(stored.get("repository_tree_id") or ""),
            task_aliases=actual_slice,
            held_task_aliases=hold_projection["held_task_aliases"],
            held_set_sha256=hold_projection["held_set_sha256"],
        )
    except RuntimeError:
        return False, "master_execution_slice_is_invalid"
    if (
        stored.get("execution_slice_sha256") != actual_slice_digest
        or _safe_int(stored.get("execution_slice_task_count")) != len(actual_slice)
        or stored.get("authorization_held_set_sha256")
        != hold_projection["held_set_sha256"]
        or _safe_int(stored.get("authorization_held_task_count"), -1)
        != len(hold_projection["held_task_aliases"])
        or stored.get("bootstrap_completion_evidence_id")
        != expected_bootstrap_evidence_id
        or actual_bootstrap_evidence_id != expected_bootstrap_evidence_id
    ):
        return False, "stored_master_execution_slice_mismatch"
    return True, "bound_process_live"


def _write_master_identity(pid: int, snapshot: Any) -> None:
    actual = _process_birth_identity(pid)
    if actual is None or not _actual_master_command_matches(actual):
        raise RuntimeError("detached master process does not match the launch command")
    python_environment = _process_python_environment(pid)
    if python_environment != _sealed_python_environment():
        raise RuntimeError("detached master process has a foreign Python environment")
    actual_argv = _logical_sealed_python_argv(
        tuple(str(item) for item in actual.get("argv") or ())
    )
    if actual_argv is None:
        raise RuntimeError("master process does not have the sealed launch argv")
    execution_slice = _master_execution_slice(actual_argv)
    source = _source()
    held_snapshot, hold_projection = _manual_gate_hold_projection(source)
    (
        _launch_snapshot,
        _launch_slice,
        _launch_slice_digest,
        expected_bootstrap_evidence_id,
    ) = _task_source_launch_contract(source)
    actual_bootstrap_evidence_id = _master_single_common_arg_value(
        actual_argv,
        "--duckdb-bootstrap-completion-evidence-id",
    )
    if actual_bootstrap_evidence_id != expected_bootstrap_evidence_id:
        raise RuntimeError("master bootstrap completion evidence changed at launch")
    if (
        held_snapshot.plan_root_cid != snapshot.plan_root_cid
        or held_snapshot.repository_tree_id != snapshot.repository_tree_id
    ):
        raise RuntimeError("manual-gate held set changed across master launch")
    execution_slice_digest = _execution_slice_digest(
        plan_root_cid=str(snapshot.plan_root_cid),
        repository_tree_id=str(snapshot.repository_tree_id),
        task_aliases=execution_slice,
        held_task_aliases=hold_projection["held_task_aliases"],
        held_set_sha256=hold_projection["held_set_sha256"],
    )
    payload = {
        "schema": "ipfs_datasets_py/duckdb-quack-master-identity@3",
        "program_id": PROGRAM_ID,
        "repository_root": str(REPO_ROOT),
        "master_root": str(MASTER_ROOT),
        "master_pid_path": str(MASTER_PID),
        "plan_root_cid": snapshot.plan_root_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "execution_slice_sha256": execution_slice_digest,
        "execution_slice_task_count": len(execution_slice),
        "authorization_held_set_sha256": hold_projection["held_set_sha256"],
        "authorization_held_task_count": len(
            hold_projection["held_task_aliases"]
        ),
        "bootstrap_completion_evidence_id": expected_bootstrap_evidence_id,
        "lane_count": _safe_int(
            _option_value(
                actual_argv,
                "--implementation-supervisor-lanes-per-track",
            )
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_environment_sha256": (
            f"sha256:{_sha256_text(_canonical_json(python_environment))}"
        ),
        **{key: actual[key] for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")},
    }
    _atomic_write_text(MASTER_IDENTITY, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"error": "unreadable"}
    return payload if isinstance(payload, dict) else {"error": "non_object"}


def _retry_lifecycle_paths() -> tuple[Path, Path]:
    """Return paths below the complete, permit-bound runtime generation.

    Keep this dynamic instead of deriving it from ``STATE_ROOT``: the reset
    authority deliberately binds the database, master, and every lane as
    siblings below ``RUNTIME_ROOT``.
    """

    root = RUNTIME_ROOT.resolve()
    return (
        root / "duckdb-retry-reset/journals/lifecycle",
        root / ".duckdb-retry-reset.lifecycle.lock",
    )


def _strict_regular_bytes(
    path: Path,
    *,
    noun: str,
    maximum_bytes: int = 2 * 1024 * 1024,
    required_mode: int | None = None,
    required_uid: int | None = None,
    forbidden_mode: int = 0,
) -> bytes:
    """Read a bounded regular file without following or racing a symlink."""

    import stat

    try:
        before = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{noun} is missing: {path}") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size <= 0
        or before.st_size > maximum_bytes
    ):
        raise RuntimeError(f"{noun} is not a bounded regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"cannot open {noun}: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise RuntimeError(f"{noun} changed while opening: {path}")
        if required_mode is not None and stat.S_IMODE(opened.st_mode) != required_mode:
            raise RuntimeError(f"{noun} has unsafe permissions: {path}")
        if required_uid is not None and opened.st_uid != required_uid:
            raise RuntimeError(f"{noun} has an unsafe owner: {path}")
        if forbidden_mode and opened.st_mode & forbidden_mode:
            raise RuntimeError(f"{noun} has unsafe permissions: {path}")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            or len(payload) != opened.st_size
        ):
            raise RuntimeError(f"{noun} changed while reading: {path}")
        if required_mode is not None and stat.S_IMODE(after.st_mode) != required_mode:
            raise RuntimeError(f"{noun} permissions changed while reading: {path}")
        if required_uid is not None and after.st_uid != required_uid:
            raise RuntimeError(f"{noun} owner changed while reading: {path}")
        if forbidden_mode and after.st_mode & forbidden_mode:
            raise RuntimeError(f"{noun} permissions changed while reading: {path}")
        final = path.lstat()
        if (final.st_dev, final.st_ino) != (opened.st_dev, opened.st_ino):
            raise RuntimeError(f"{noun} was replaced while reading: {path}")
        if required_mode is not None and stat.S_IMODE(final.st_mode) != required_mode:
            raise RuntimeError(f"{noun} has unsafe final permissions: {path}")
        if required_uid is not None and final.st_uid != required_uid:
            raise RuntimeError(f"{noun} has an unsafe final owner: {path}")
        if forbidden_mode and final.st_mode & forbidden_mode:
            raise RuntimeError(f"{noun} has unsafe final permissions: {path}")
    finally:
        os.close(descriptor)
    if not payload or len(payload) > maximum_bytes:
        raise RuntimeError(f"{noun} has an invalid size: {path}")
    return payload


def _strict_json_file(path: Path, *, noun: str) -> tuple[dict[str, Any], bytes]:
    encoded = _strict_regular_bytes(path, noun=noun)
    try:
        payload = _strict_json_object(encoded.decode("utf-8"), noun=noun)
    except UnicodeError as exc:
        raise RuntimeError(f"{noun} is not UTF-8") from exc
    return payload, encoded


def _retry_checkout_module() -> Any:
    return _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.checkout_lock",
        "ipfs_accelerate_py.agent_supervisor.checkout_lock",
    )


def _retry_git_at(repository_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _canonical_retry_checkout_lock_path(
    checkout_module: Any, repository_root: Path
) -> Path:
    declared = Path(checkout_module.checkout_mutation_lock_path(repository_root))
    parent = declared.parent.resolve(strict=True)
    return parent / declared.name


def _retry_checkout_snapshot() -> list[dict[str, Any]]:
    """Capture both independently mutable checkouts and their common locks."""

    checkout_module = _retry_checkout_module()
    parent_root = REPO_ROOT.resolve()
    accelerator_root = ACCELERATE_ROOT.resolve()
    if not accelerator_root.is_dir():
        raise RuntimeError("retry lifecycle requires the initialized accelerator checkout")
    parent_gitlink = _head_gitlink_commit("ipfs_accelerate_py")
    records: list[dict[str, Any]] = []
    for role, root in (("parent", parent_root), ("accelerator", accelerator_root)):
        branch = _retry_git_at(root, "branch", "--show-current")
        if not branch:
            raise RuntimeError(f"retry lifecycle {role} checkout is detached")
        dirty = _retry_git_at(root, "status", "--porcelain=v1")
        if dirty:
            raise RuntimeError(f"retry lifecycle {role} checkout is not clean")
        records.append(
            {
                "role": role,
                "repository_root": str(root),
                "repository_id": checkout_module.checkout_repository_id(root),
                "lock_path": str(
                    _canonical_retry_checkout_lock_path(checkout_module, root)
                ),
                "branch": branch,
                "head_commit": _retry_git_at(root, "rev-parse", "--verify", "HEAD"),
                "head_tree": _retry_git_at(
                    root, "rev-parse", "--verify", "HEAD^{tree}"
                ),
                "parent_accelerator_gitlink": parent_gitlink,
            }
        )
    by_role = {str(item["role"]): item for item in records}
    if set(by_role) != {"parent", "accelerator"} or len(records) != 2:
        raise RuntimeError("retry checkout binding must name exactly two repositories")
    if by_role["parent"]["branch"] != TARGET_BRANCH:
        raise RuntimeError("retry lifecycle requires the canonical parent branch")
    if by_role["accelerator"]["head_commit"] != parent_gitlink:
        raise RuntimeError("retry lifecycle accelerator checkout/gitlink differ")
    lock_paths = [str(item["lock_path"]) for item in records]
    if len(set(lock_paths)) != len(lock_paths):
        raise RuntimeError("retry checkout mutation lock paths are not independent")
    return sorted(records, key=lambda item: str(item["lock_path"]))


def _retry_checkout_lock_preflight() -> str:
    """Validate both canonical common dirs without requiring an active retry."""

    import stat

    checkout_module = _retry_checkout_module()
    details: list[str] = []
    errors: list[str] = []
    for role, root in (
        ("parent", REPO_ROOT.resolve()),
        ("accelerator", ACCELERATE_ROOT.resolve()),
    ):
        lock_path = _canonical_retry_checkout_lock_path(checkout_module, root)
        binding = {
            "role": role,
            "repository_root": str(root),
            "repository_id": checkout_module.checkout_repository_id(root),
            "lock_path": str(lock_path),
        }
        try:
            _assert_retry_checkout_lock_authority(
                binding, lock_path, require_guard=False
            )
        except (OSError, RuntimeError) as exc:
            errors.append(f"{role}:{type(exc).__name__}: {exc}")
            continue
        metadata = lock_path.parent.lstat()
        details.append(
            f"{role}:path={lock_path.parent},"
            f"mode={stat.S_IMODE(metadata.st_mode):04o},"
            f"uid={metadata.st_uid},gid={metadata.st_gid}"
        )
    if errors:
        raise RuntimeError("; ".join(errors))
    return "; ".join(details)


def _assert_retry_checkout_lock_authority(
    binding: Mapping[str, Any],
    lock_path: Path,
    *,
    require_guard: bool = True,
) -> None:
    """Rederive one canonical common-dir lock and inspect its guard in-place."""

    import stat

    checkout_module = _retry_checkout_module()
    role = str(binding.get("role") or "")
    expected_root = {
        "parent": REPO_ROOT.resolve(),
        "accelerator": ACCELERATE_ROOT.resolve(),
    }.get(role)
    if expected_root is None:
        raise RuntimeError("retry checkout lease has an unknown repository role")
    canonical_lock = _canonical_retry_checkout_lock_path(
        checkout_module, expected_root
    )
    if (
        str(binding.get("repository_root") or "") != str(expected_root)
        or binding.get("repository_id")
        != checkout_module.checkout_repository_id(expected_root)
        or lock_path != canonical_lock
        or str(binding.get("lock_path") or "") != str(canonical_lock)
    ):
        raise RuntimeError("retry checkout lock path/repository binding is not canonical")
    common_metadata = canonical_lock.parent.lstat()
    if (
        stat.S_ISLNK(common_metadata.st_mode)
        or not stat.S_ISDIR(common_metadata.st_mode)
        or common_metadata.st_uid != os.geteuid()
        or common_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RuntimeError(
            "retry checkout git-common directory is not owner-controlled: "
            f"path={canonical_lock.parent} "
            f"mode={stat.S_IMODE(common_metadata.st_mode):04o} "
            f"uid={common_metadata.st_uid} gid={common_metadata.st_gid}"
        )
    guard_path = canonical_lock.with_name(f".{canonical_lock.name}.update.lock")
    if not require_guard:
        return
    guard_metadata = guard_path.lstat()
    if (
        stat.S_ISLNK(guard_metadata.st_mode)
        or not stat.S_ISREG(guard_metadata.st_mode)
        or guard_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(guard_metadata.st_mode) != 0o600
    ):
        raise RuntimeError(
            "retry checkout serialized-update guard is unsafe: "
            f"path={guard_path} mode={stat.S_IMODE(guard_metadata.st_mode):04o} "
            f"uid={guard_metadata.st_uid} gid={guard_metadata.st_gid}"
        )


def _assert_retry_checkout_snapshot(journal: Mapping[str, Any]) -> None:
    expected = journal.get("checkout_binding")
    if not isinstance(expected, list) or _retry_checkout_snapshot() != expected:
        raise RuntimeError(
            "retry checkout branch/HEAD/tree/clean/gitlink changed while leased"
        )


def _retry_checkout_owner_cid(owner: Mapping[str, Any]) -> str:
    material = dict(owner)
    claimed = material.pop("owner_cid", "")
    derived = "sha256:" + _sha256_text(_canonical_json(material))
    if claimed and claimed != derived:
        raise RuntimeError("retry checkout lease owner CID is invalid")
    return derived


def _retry_checkout_lease_cid(lease: Mapping[str, Any]) -> str:
    material = dict(lease)
    claimed = material.pop("lease_cid", "")
    material.pop("record_cid", None)
    material.pop("generation", None)
    material.pop("owner_history", None)
    derived = "sha256:" + _sha256_text(_canonical_json(material))
    if claimed and claimed != derived:
        raise RuntimeError("retry checkout lease CID is invalid")
    return derived


def _retry_checkout_lease_record_cid(lease: Mapping[str, Any]) -> str:
    material = dict(lease)
    claimed = material.pop("record_cid", "")
    derived = "sha256:" + _sha256_text(_canonical_json(material))
    if claimed and claimed != derived:
        raise RuntimeError("retry checkout lease record CID is invalid")
    return derived


def _retry_checkout_tombstone_cid(tombstone: Mapping[str, Any]) -> str:
    material = dict(tombstone)
    claimed = material.pop("tombstone_cid", "")
    derived = "sha256:" + _sha256_text(_canonical_json(material))
    if claimed and claimed != derived:
        raise RuntimeError("retry checkout release tombstone CID is invalid")
    return derived


def _retry_checkout_release_receipt_cid(receipt: Mapping[str, Any]) -> str:
    material = dict(receipt)
    claimed = material.pop("receipt_cid", "")
    derived = "sha256:" + _sha256_text(_canonical_json(material))
    if claimed and claimed != derived:
        raise RuntimeError("retry checkout release receipt CID is invalid")
    return derived


def _retry_checkout_finalization_cid(finalization: Mapping[str, Any]) -> str:
    material = dict(finalization)
    claimed = material.pop("finalization_cid", "")
    derived = "sha256:" + _sha256_text(_canonical_json(material))
    if claimed and claimed != derived:
        raise RuntimeError("retry checkout finalization CID is invalid")
    return derived


def _retry_checkout_owner_record(
    identity: Mapping[str, Any],
    *,
    generation: int,
    previous_owner_cid: str,
) -> dict[str, Any]:
    owner: dict[str, Any] = {
        "schema": RETRY_CHECKOUT_LEASE_OWNER_SCHEMA,
        "generation": generation,
        "previous_owner_cid": previous_owner_cid,
        "adopted_at": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "pid": identity.get("pid"),
            "boot_id": identity.get("boot_id"),
            "start_ticks": identity.get("start_ticks"),
            "cmdline_sha256": identity.get("cmdline_sha256"),
            "argv": [str(item) for item in identity.get("argv") or ()],
        },
    }
    owner["owner_cid"] = _retry_checkout_owner_cid(owner)
    return owner


def _retry_checkout_lease_id(
    journal: Mapping[str, Any], binding: Mapping[str, Any]
) -> str:
    return "sha256:" + _sha256_text(
        _canonical_json(
            {
                "namespace": "duckdb-quack-retry-checkout-lease",
                "request_digest": journal.get("request_digest"),
                "intent_cid": journal.get("intent_cid"),
                "repository_id": binding.get("repository_id"),
                "lock_path": binding.get("lock_path"),
            }
        )
    )


def _new_retry_checkout_lease(
    journal: Mapping[str, Any],
    binding: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    owner = _retry_checkout_owner_record(
        identity, generation=1, previous_owner_cid=""
    )
    lease: dict[str, Any] = {
        "schema": RETRY_CHECKOUT_LEASE_SCHEMA,
        "kind": "ipfs-datasets-duckdb-quack-retry",
        "program_id": PROGRAM_ID,
        "request_id": journal.get("request_id"),
        "request_digest": journal.get("request_digest"),
        "intent_cid": journal.get("intent_cid"),
        "repository_role": binding.get("role"),
        "repository_id": binding.get("repository_id"),
        "repository_root": binding.get("repository_root"),
        "lock_path": binding.get("lock_path"),
        "checkout_binding": dict(binding),
        "task": dict(journal.get("task") or {}),
        "writer": dict(journal.get("writer") or {}),
        "lease_id": _retry_checkout_lease_id(journal, binding),
        "generation": 1,
        "owner_history": [owner],
    }
    lease["lease_cid"] = _retry_checkout_lease_cid(lease)
    lease["record_cid"] = _retry_checkout_lease_record_cid(lease)
    return lease


def _validate_retry_checkout_lease(
    lease: Mapping[str, Any],
    *,
    journal: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {
        "schema",
        "kind",
        "program_id",
        "request_id",
        "request_digest",
        "intent_cid",
        "repository_role",
        "repository_id",
        "repository_root",
        "lock_path",
        "checkout_binding",
        "task",
        "writer",
        "lease_id",
        "generation",
        "owner_history",
        "lease_cid",
        "record_cid",
    }
    generation = lease.get("generation")
    history = lease.get("owner_history")
    expected = {
        "schema": RETRY_CHECKOUT_LEASE_SCHEMA,
        "kind": "ipfs-datasets-duckdb-quack-retry",
        "program_id": PROGRAM_ID,
        "request_id": journal.get("request_id"),
        "request_digest": journal.get("request_digest"),
        "intent_cid": journal.get("intent_cid"),
        "repository_role": binding.get("role"),
        "repository_id": binding.get("repository_id"),
        "repository_root": binding.get("repository_root"),
        "lock_path": binding.get("lock_path"),
        "checkout_binding": dict(binding),
        "task": dict(journal.get("task") or {}),
        "writer": dict(journal.get("writer") or {}),
        "lease_id": _retry_checkout_lease_id(journal, binding),
    }
    if (
        set(lease) != allowed
        or any(lease.get(key) != value for key, value in expected.items())
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation <= 0
        or not isinstance(history, list)
        or len(history) != generation
        or generation > 32
    ):
        raise RuntimeError("retry checkout lease is foreign or malformed")
    previous = ""
    for index, owner in enumerate(history, 1):
        if not isinstance(owner, Mapping) or set(owner) != {
            "schema",
            "generation",
            "previous_owner_cid",
            "adopted_at",
            "identity",
            "owner_cid",
        }:
            raise RuntimeError("retry checkout lease owner history is malformed")
        identity = owner.get("identity")
        if (
            owner.get("schema") != RETRY_CHECKOUT_LEASE_OWNER_SCHEMA
            or owner.get("generation") != index
            or owner.get("previous_owner_cid") != previous
            or not isinstance(owner.get("adopted_at"), str)
            or not owner.get("adopted_at")
            or not isinstance(identity, Mapping)
            or set(identity)
            != {"pid", "boot_id", "start_ticks", "cmdline_sha256", "argv"}
            or not isinstance(identity.get("pid"), int)
            or isinstance(identity.get("pid"), bool)
            or identity.get("pid", 0) <= 0
            or not isinstance(identity.get("boot_id"), str)
            or not identity.get("boot_id")
            or not isinstance(identity.get("start_ticks"), int)
            or isinstance(identity.get("start_ticks"), bool)
            or identity.get("start_ticks", 0) <= 0
            or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(identity.get("cmdline_sha256") or "")
            )
            or not isinstance(identity.get("argv"), list)
            or not all(isinstance(item, str) for item in identity.get("argv") or ())
            or owner.get("owner_cid") != _retry_checkout_owner_cid(owner)
        ):
            raise RuntimeError("retry checkout lease owner history is not content-bound")
        previous = str(owner["owner_cid"])
    if lease.get("lease_cid") != _retry_checkout_lease_cid(lease):
        raise RuntimeError("retry checkout lease is not content-bound")
    if lease.get("record_cid") != _retry_checkout_lease_record_cid(lease):
        raise RuntimeError("retry checkout lease owner record is not content-bound")
    return dict(lease)


def _durable_retry_lifecycle_write(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably replace one lifecycle record below its fixed runtime root."""

    import stat

    lifecycle_root, _lock_path = _retry_lifecycle_paths()
    try:
        path.absolute().relative_to(lifecycle_root.absolute())
    except ValueError as exc:
        raise RuntimeError("retry lifecycle journal escapes its governed root") from exc
    current = RUNTIME_ROOT.resolve()
    root_metadata = current.lstat()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.geteuid()
        or root_metadata.st_mode & stat.S_IWOTH
    ):
        raise RuntimeError("RUNTIME_ROOT is not owner-controlled")
    try:
        relative_parent = path.parent.absolute().relative_to(current)
    except ValueError as exc:
        raise RuntimeError("retry lifecycle parent escapes RUNTIME_ROOT") from exc
    for part in relative_parent.parts:
        parent = current
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            continue
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & stat.S_IWOTH
        ):
            raise RuntimeError(f"retry lifecycle parent is unsafe: {current}")
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode)
    ):
        raise RuntimeError("retry lifecycle journal target is unsafe")
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )


def _read_retry_checkout_lock(path: Path) -> dict[str, Any]:
    encoded = _strict_regular_bytes(
        path,
        noun="retry checkout mutation lease",
        required_mode=0o600,
        required_uid=os.geteuid(),
    )
    try:
        return _strict_json_object(
            encoded.decode("utf-8"), noun="retry checkout mutation lease"
        )
    except UnicodeError as exc:
        raise RuntimeError("retry checkout mutation lease is not UTF-8") from exc


def _read_owner_controlled_checkout_json(path: Path, *, noun: str) -> dict[str, Any]:
    import stat

    encoded = _strict_regular_bytes(
        path,
        noun=noun,
        required_uid=os.geteuid(),
        forbidden_mode=stat.S_IWGRP | stat.S_IWOTH,
    )
    try:
        return _strict_json_object(encoded.decode("utf-8"), noun=noun)
    except UnicodeError as exc:
        raise RuntimeError(f"{noun} is not UTF-8") from exc


def _create_retry_checkout_lock(path: Path, payload: Mapping[str, Any]) -> None:
    """Exclusively create and durably publish one no-follow lock record."""

    import stat

    parent = path.parent
    parent_metadata = parent.lstat()
    if (
        stat.S_ISLNK(parent_metadata.st_mode)
        or not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or parent_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RuntimeError("retry checkout mutation lock parent is unsafe")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError("retry checkout mutation lock creation raced") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise RuntimeError("new retry checkout mutation lock is unsafe")
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("retry checkout mutation lock write was incomplete")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _replace_retry_checkout_lock(path: Path, payload: Mapping[str, Any]) -> None:
    import stat

    existing = path.lstat()
    if (
        stat.S_ISLNK(existing.st_mode)
        or not stat.S_ISREG(existing.st_mode)
        or existing.st_uid != os.geteuid()
        or stat.S_IMODE(existing.st_mode) != 0o600
    ):
        raise RuntimeError("retry checkout mutation lease is not owner-controlled")
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise RuntimeError("adopted retry checkout mutation lease is unsafe")


def _retry_checkout_binding_by_path(
    journal: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    bindings = journal.get("checkout_binding")
    if not isinstance(bindings, list) or len(bindings) != 2:
        raise RuntimeError("retry lifecycle checkout binding is malformed")
    result: dict[str, dict[str, Any]] = {}
    for item in bindings:
        if not isinstance(item, Mapping) or set(item) != {
            "role",
            "repository_root",
            "repository_id",
            "lock_path",
            "branch",
            "head_commit",
            "head_tree",
            "parent_accelerator_gitlink",
        }:
            raise RuntimeError("retry lifecycle checkout binding is malformed")
        role = str(item.get("role") or "")
        lock_path = str(item.get("lock_path") or "")
        if (
            role not in {"parent", "accelerator"}
            or not lock_path
            or lock_path in result
            or not item.get("repository_id")
            or not item.get("repository_root")
            or not item.get("branch")
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(item.get("head_commit") or ""))
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(item.get("head_tree") or ""))
            or not re.fullmatch(
                r"[0-9a-f]{40}|[0-9a-f]{64}",
                str(item.get("parent_accelerator_gitlink") or ""),
            )
        ):
            raise RuntimeError("retry lifecycle checkout binding is incomplete")
        result[lock_path] = dict(item)
    if {item["role"] for item in result.values()} != {"parent", "accelerator"}:
        raise RuntimeError("retry lifecycle checkout roles are incomplete")
    return result


def _retry_checkout_lease_records(
    journal: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    bindings = _retry_checkout_binding_by_path(journal)
    records = journal.get("checkout_leases", [])
    if not isinstance(records, list) or len(records) > len(bindings):
        raise RuntimeError("retry checkout lease collection is malformed")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise RuntimeError("retry checkout lease collection is malformed")
        lock_path = str(record.get("lock_path") or "")
        binding = bindings.get(lock_path)
        if binding is None or lock_path in result:
            raise RuntimeError("retry checkout lease path is foreign or duplicated")
        result[lock_path] = _validate_retry_checkout_lease(
            record, journal=journal, binding=binding
        )
    if [str(item.get("lock_path") or "") for item in records] != sorted(result):
        raise RuntimeError("retry checkout leases are not canonically ordered")
    return result


def _same_retry_checkout_owner(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> bool:
    return all(
        first.get(key) == second.get(key)
        for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
    )


def _adopt_retry_checkout_lease(
    lease: Mapping[str, Any], identity: Mapping[str, Any]
) -> dict[str, Any]:
    history = [dict(item) for item in lease["owner_history"]]
    previous_identity = history[-1]["identity"]
    if _same_retry_checkout_owner(previous_identity, identity):
        return dict(lease)
    if _identity_is_live(previous_identity):
        raise RuntimeError("another retry checkout lease owner is still live")
    generation = int(lease["generation"]) + 1
    if generation > 32:
        raise RuntimeError("retry checkout lease owner history is exhausted")
    history.append(
        _retry_checkout_owner_record(
            identity,
            generation=generation,
            previous_owner_cid=str(history[-1]["owner_cid"]),
        )
    )
    adopted = {
        **dict(lease),
        "generation": generation,
        "owner_history": history,
    }
    adopted.pop("record_cid", None)
    adopted["record_cid"] = _retry_checkout_lease_record_cid(adopted)
    return adopted


def _reconcile_retry_checkout_lease_record(
    expected: Mapping[str, Any],
    candidate: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    """Accept only a crash-published, exact extension of the journal history."""

    if candidate == expected:
        return dict(candidate)
    expected_history = expected.get("owner_history")
    candidate_history = candidate.get("owner_history")
    if (
        expected.get("lease_cid") != candidate.get("lease_cid")
        or not isinstance(expected_history, list)
        or not isinstance(candidate_history, list)
        or len(candidate_history) <= len(expected_history)
        or candidate_history[: len(expected_history)] != expected_history
        or candidate.get("generation") != len(candidate_history)
        or expected.get("generation") != len(expected_history)
    ):
        raise RuntimeError(
            "retry checkout mutation lease differs from its journal"
        )
    extension = candidate_history[len(expected_history) :]
    for index, owner in enumerate(extension):
        identity = owner["identity"]
        same_current = _same_retry_checkout_owner(identity, current)
        if same_current and index != len(extension) - 1:
            raise RuntimeError(
                "retry checkout lease history extends a still-live owner"
            )
        if not same_current and _identity_is_live(identity):
            raise RuntimeError(
                "retry checkout lease history contains a foreign live owner"
            )
    return dict(candidate)


def _acquire_or_adopt_retry_checkout_leases(
    context: Mapping[str, Any],
    journal: dict[str, Any],
    *,
    path: Path,
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    """Acquire both checkout locks in deterministic common-directory order."""

    checkout_module = _retry_checkout_module()
    bindings = _retry_checkout_binding_by_path(journal)
    records = _retry_checkout_lease_records(journal)
    current = _current_owner_identity()
    for lock_text in sorted(bindings):
        lock_path = Path(lock_text)
        binding = bindings[lock_text]
        expected_record = records.get(lock_text)
        _assert_retry_checkout_lock_authority(
            binding, lock_path, require_guard=False
        )
        with checkout_module.serialized_lock_update(lock_path):
            _assert_retry_checkout_lock_authority(binding, lock_path)
            try:
                lock_path.lstat()
            except FileNotFoundError:
                stored = None
            else:
                stored = _read_retry_checkout_lock(lock_path)
            if stored is None:
                if expected_record is not None:
                    raise RuntimeError(
                        "held retry checkout mutation lease disappeared before release"
                    )
                candidate = _new_retry_checkout_lease(journal, binding, current)
                _create_retry_checkout_lock(lock_path, candidate)
            else:
                candidate = _validate_retry_checkout_lease(
                    stored, journal=journal, binding=binding
                )
                if expected_record is not None:
                    candidate = _reconcile_retry_checkout_lease_record(
                        expected_record, candidate, current
                    )
                candidate = _adopt_retry_checkout_lease(candidate, current)
                if candidate != stored:
                    _replace_retry_checkout_lock(lock_path, candidate)
                    if fault_injector:
                        fault_injector(
                            "checkout_lease_adopted_physical:"
                            + str(binding["role"])
                        )
            records[lock_text] = candidate
        journal["checkout_leases"] = [
            records[item] for item in sorted(records)
        ]
        journal["updated_at"] = datetime.now(timezone.utc).isoformat()
        _durable_retry_lifecycle_write(path, journal)
        if fault_injector:
            fault_injector(
                "checkout_lease_acquired:" + str(binding["role"])
            )
    if set(records) != set(bindings):
        raise RuntimeError("retry lifecycle did not acquire every checkout lease")
    if fault_injector:
        fault_injector("checkout_leases_acquired")
    _assert_retry_checkout_snapshot(journal)
    _assert_retry_checkout_leases(journal)
    if journal["phase"] == "drained":
        journal["checkout_leased_at"] = datetime.now(timezone.utc).isoformat()
        journal["checkout_lease_set_cid"] = _retry_checkout_lease_set_cid(journal)
        journal["phase"] = "leased"
        journal["updated_at"] = journal["checkout_leased_at"]
        _durable_retry_lifecycle_write(path, journal)
        if fault_injector:
            fault_injector("leased")
    return journal


def _assert_retry_checkout_leases(journal: Mapping[str, Any]) -> None:
    checkout_module = _retry_checkout_module()
    bindings = _retry_checkout_binding_by_path(journal)
    records = _retry_checkout_lease_records(journal)
    if set(records) != set(bindings):
        raise RuntimeError("retry lifecycle does not hold both checkout leases")
    current = _current_owner_identity()
    for lock_text in sorted(bindings):
        lock_path = Path(lock_text)
        _assert_retry_checkout_lock_authority(
            bindings[lock_text], lock_path, require_guard=False
        )
        with checkout_module.serialized_lock_update(lock_path):
            _assert_retry_checkout_lock_authority(
                bindings[lock_text], lock_path
            )
            stored = _read_retry_checkout_lock(lock_path)
            if stored != records[lock_text]:
                raise RuntimeError(
                    "retry checkout mutation lease changed while held"
                )
            last_owner = records[lock_text]["owner_history"][-1]["identity"]
            if not _same_retry_checkout_owner(last_owner, current):
                raise RuntimeError(
                    "retry checkout mutation lease is not owned by this lifecycle"
                )


def _retry_lifecycle_request_digest(request: Any) -> str:
    try:
        encoded = bytes(request.canonical_bytes())
    except Exception as exc:
        raise RuntimeError("retry request has no canonical byte representation") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _retry_lifecycle_journal_path(request: Any) -> Path:
    digest = _retry_lifecycle_request_digest(request)
    lifecycle_root, _lock_path = _retry_lifecycle_paths()
    return lifecycle_root / f"{digest.removeprefix('sha256:')}.json"


def _retry_lifecycle_intent_material(journal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": RETRY_LIFECYCLE_SCHEMA,
        "program_id": journal.get("program_id"),
        "request_id": journal.get("request_id"),
        "request_digest": journal.get("request_digest"),
        "repository_root": journal.get("repository_root"),
        "runtime_root": journal.get("runtime_root"),
        "database_path": journal.get("database_path"),
        "plan_root_cid": journal.get("plan_root_cid"),
        "task_source_repository_tree_id": journal.get(
            "task_source_repository_tree_id"
        ),
        "repository_head_commit": journal.get("repository_head_commit"),
        "repository_head_tree": journal.get("repository_head_tree"),
        "checkout_binding": journal.get("checkout_binding"),
        "task": journal.get("task"),
        "writer": journal.get("writer"),
        "owner_configuration": journal.get("owner_configuration"),
        "policy": journal.get("policy"),
        "authorization": journal.get("authorization"),
        "environment": journal.get("environment"),
        "old_master": journal.get("old_master"),
        "old_process_tree": journal.get("old_process_tree"),
    }


def _retry_lifecycle_intent_cid(journal: Mapping[str, Any]) -> str:
    return "sha256:" + _sha256_text(
        _canonical_json(_retry_lifecycle_intent_material(journal))
    )


def _retry_execution_intent_binding_record(
    journal: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the immutable released execution-intent pointer in a parent."""

    module = _retry_reset_module()
    record = journal.get("execution_intent")
    required = {
        "schema",
        "execution_intent_cid",
        "projection_path",
        "request_digest",
        "parent_intent_cid",
        "preparation_event",
    }
    if (
        not isinstance(record, Mapping)
        or set(record) != required
        or record.get("schema")
        != module.RETRY_RESET_EXECUTION_INTENT_BINDING_SCHEMA
        or record.get("request_digest") != journal.get("request_digest")
        or record.get("parent_intent_cid") != journal.get("intent_cid")
    ):
        raise RuntimeError("retry lifecycle execution-intent binding is malformed")
    intent_cid = record.get("execution_intent_cid")
    runtime_root = Path(str(journal.get("runtime_root") or ""))
    expected_path = runtime_root / (
        "duckdb-retry-reset/execution-intents/" + str(intent_cid) + ".json"
    )
    event = record.get("preparation_event")
    if (
        not isinstance(intent_cid, str)
        or not re.fullmatch(r"b[a-z2-7]{20,100}", intent_cid)
        or not runtime_root.is_absolute()
        or record.get("projection_path") != str(expected_path)
        or not isinstance(event, Mapping)
        or set(event) != {"event_cid", "sequence", "revision"}
        or not isinstance(event.get("event_cid"), str)
        or not re.fullmatch(
            r"b[a-z2-7]{20,100}", str(event.get("event_cid") or "")
        )
        or not isinstance(event.get("sequence"), int)
        or isinstance(event.get("sequence"), bool)
        or event.get("sequence", -1) < 0
        or not isinstance(event.get("revision"), int)
        or isinstance(event.get("revision"), bool)
        or event.get("revision", -1) < 0
    ):
        raise RuntimeError("retry lifecycle execution-intent event is malformed")
    return dict(record)


def _retry_lifecycle_phase_cid(namespace: str, payload: Mapping[str, Any]) -> str:
    return "sha256:" + _sha256_text(
        _canonical_json({"namespace": namespace, **dict(payload)})
    )


def _retry_lifecycle_drain_cid(journal: Mapping[str, Any]) -> str:
    return _retry_lifecycle_phase_cid(
        "duckdb-quack-retry-drain",
        {
            "intent_cid": journal.get("intent_cid"),
            "drain_process_tree": journal.get("drain_process_tree"),
            "drain_started_at": journal.get("drain_started_at"),
        },
    )


def _retry_lifecycle_drained_cid(journal: Mapping[str, Any]) -> str:
    return _retry_lifecycle_phase_cid(
        "duckdb-quack-retry-drained",
        {
            "drain_cid": journal.get("drain_cid"),
            "drained_at": journal.get("drained_at"),
        },
    )


def _retry_reset_anchor_cid(anchor: Mapping[str, Any]) -> str:
    material = dict(anchor)
    claimed = material.pop("anchor_cid", "")
    derived = "sha256:" + _sha256_text(_canonical_json(material))
    if claimed and claimed != derived:
        raise RuntimeError("retry-reset anchor CID is invalid")
    return derived


def _retry_lifecycle_reset_commit_cid(journal: Mapping[str, Any]) -> str:
    return _retry_lifecycle_phase_cid(
        "duckdb-quack-retry-reset-commit",
        {
            "drained_cid": journal.get("drained_cid"),
            "checkout_lease_set_cid": journal.get("checkout_lease_set_cid"),
            "retry_reset_receipt": journal.get("retry_reset_receipt"),
            "retry_reset_anchor": journal.get("retry_reset_anchor"),
            "reset_committed_at": journal.get("reset_committed_at"),
        },
    )


def _retry_checkout_lease_set_cid(journal: Mapping[str, Any]) -> str:
    return _retry_lifecycle_phase_cid(
        "duckdb-quack-retry-checkout-lease-set",
        {
            "drained_cid": journal.get("drained_cid"),
            "checkout_lease_cids": [
                item.get("lease_cid")
                for item in journal.get("checkout_leases") or ()
            ],
            "checkout_leased_at": journal.get("checkout_leased_at"),
        },
    )


def _retry_lifecycle_relaunch_intent_cid(journal: Mapping[str, Any]) -> str:
    return _retry_lifecycle_phase_cid(
        "duckdb-quack-retry-relaunch",
        {
            "reset_commit_cid": journal.get("reset_commit_cid"),
            "relaunch": journal.get("relaunch"),
        },
    )


def _read_retry_lifecycle_journal(
    path: Path,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    payload, _encoded = _strict_json_file(path, noun="retry lifecycle journal")
    import stat

    metadata = path.lstat()
    if (
        metadata.st_uid != os.geteuid()
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RuntimeError("retry lifecycle journal is not owner-controlled")
    digest_from_name = f"sha256:{path.stem}"
    if (
        payload.get("schema") != RETRY_LIFECYCLE_SCHEMA
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("phase") not in RETRY_LIFECYCLE_PHASES
        or payload.get("request_digest") != digest_from_name
        or payload.get("intent_cid") != _retry_lifecycle_intent_cid(payload)
    ):
        raise RuntimeError(f"retry lifecycle journal is malformed: {path}")
    allowed_fields = {
        "schema",
        "program_id",
        "phase",
        "request_id",
        "request_digest",
        "request_file_digest",
        "repository_root",
        "runtime_root",
        "database_path",
        "plan_root_cid",
        "task_source_repository_tree_id",
        "repository_head_commit",
        "repository_head_tree",
        "checkout_binding",
        "task",
        "writer",
        "owner_configuration",
        "policy",
        "authorization",
        "environment",
        "old_master",
        "old_process_tree",
        "lifecycle_owners",
        "created_at",
        "updated_at",
        "intent_cid",
        "execution_intent",
        "drain_process_tree",
        "drain_started_at",
        "drain_cid",
        "drained_at",
        "drained_cid",
        "retry_reset_receipt",
        "retry_reset_anchor",
        "reset_committed_at",
        "reset_commit_cid",
        "relaunch",
        "relaunch_intent_cid",
        "new_master",
        "checkout_leases",
        "checkout_leased_at",
        "checkout_lease_set_cid",
        "checkout_finalization",
        "checkout_release_tombstones",
        "checkout_release_receipt",
        "lifecycle_receipt",
    }
    if set(payload).difference(allowed_fields):
        raise RuntimeError("retry lifecycle journal contains unsupported fields")
    if request is not None and (
        payload.get("request_id") != request.request_id
        or payload.get("request_digest") != _retry_lifecycle_request_digest(request)
    ):
        raise RuntimeError("retry lifecycle journal belongs to another request")
    execution_intent = _retry_execution_intent_binding_record(payload)
    owners = payload.get("lifecycle_owners")
    if not isinstance(owners, list) or not owners or len(owners) > 32:
        raise RuntimeError("retry lifecycle owner history is malformed")
    _retry_checkout_binding_by_path(payload)
    phase_rank = {
        "prepared": 0,
        "draining": 1,
        "drained": 2,
        "leased": 3,
        "reset_committed": 4,
        "relaunching": 5,
        "finalizing": 6,
        "completed": 7,
    }[str(payload["phase"])]
    if phase_rank >= 1 and payload.get("drain_cid") != _retry_lifecycle_drain_cid(
        payload
    ):
        raise RuntimeError("retry lifecycle drain evidence is not content-bound")
    if phase_rank >= 2 and payload.get(
        "drained_cid"
    ) != _retry_lifecycle_drained_cid(payload):
        raise RuntimeError("retry lifecycle quiescence evidence is not content-bound")
    if payload["phase"] in {
        "reset_committed",
        "relaunching",
        "finalizing",
        "completed",
    }:
        receipt = payload.get("retry_reset_receipt")
        anchor = payload.get("retry_reset_anchor")
        if (
            not isinstance(receipt, Mapping)
            or not receipt.get("receipt_cid")
            or not isinstance(anchor, Mapping)
            or anchor.get("schema") != RETRY_RESET_ANCHOR_SCHEMA
            or anchor.get("receipt_cid") != receipt.get("receipt_cid")
            or anchor.get("anchor_cid") != _retry_reset_anchor_cid(anchor)
            or receipt.get("execution_intent_cid")
            != execution_intent.get("execution_intent_cid")
        ):
            raise RuntimeError("retry lifecycle reset receipt is missing")
        if payload.get("reset_commit_cid") != _retry_lifecycle_reset_commit_cid(
            payload
        ):
            raise RuntimeError("retry lifecycle reset receipt is not content-bound")
    if payload["phase"] in {"relaunching", "finalizing", "completed"}:
        relaunch = payload.get("relaunch")
        if (
            not isinstance(relaunch, Mapping)
            or not isinstance(relaunch.get("command"), list)
            or not re.fullmatch(r"[0-9a-f]{32}", str(relaunch.get("launch_token") or ""))
            or not isinstance(relaunch.get("marker"), Mapping)
        ):
            raise RuntimeError("retry lifecycle relaunch intent is malformed")
        if payload.get(
            "relaunch_intent_cid"
        ) != _retry_lifecycle_relaunch_intent_cid(payload):
            raise RuntimeError("retry lifecycle relaunch intent is not content-bound")
    if phase_rank >= 2:
        leases = _retry_checkout_lease_records(payload)
        if phase_rank >= 3 and set(leases) != set(
            _retry_checkout_binding_by_path(payload)
        ):
            raise RuntimeError("retry lifecycle checkout leases are incomplete")
        if phase_rank >= 3 and payload.get(
            "checkout_lease_set_cid"
        ) != _retry_checkout_lease_set_cid(payload):
            raise RuntimeError("retry checkout lease set is not content-bound")
    if payload["phase"] in {"finalizing", "completed"}:
        finalization = payload.get("checkout_finalization")
        if (
            not isinstance(finalization, Mapping)
            or set(finalization)
            != {
                "schema",
                "request_digest",
                "intent_cid",
                "reset_commit_cid",
                "relaunch_intent_cid",
                "checkout_lease_cids",
                "new_master",
                "finalized_at",
                "finalization_cid",
            }
            or finalization.get("schema") != RETRY_CHECKOUT_FINALIZATION_SCHEMA
            or finalization.get("request_digest") != payload.get("request_digest")
            or finalization.get("intent_cid") != payload.get("intent_cid")
            or finalization.get("reset_commit_cid")
            != payload.get("reset_commit_cid")
            or finalization.get("relaunch_intent_cid")
            != payload.get("relaunch_intent_cid")
            or not isinstance(finalization.get("finalized_at"), str)
            or not finalization.get("finalized_at")
            or finalization.get("finalization_cid")
            != _retry_checkout_finalization_cid(finalization)
            or finalization.get("checkout_lease_cids")
            != [
                lease["lease_cid"]
                for _lock_path, lease in sorted(
                    _retry_checkout_lease_records(payload).items()
                )
            ]
            or finalization.get("new_master") != payload.get("new_master")
            or not isinstance(payload.get("new_master"), Mapping)
        ):
            raise RuntimeError("retry checkout finalization is malformed")
    if payload["phase"] == "completed":
        receipt = payload.get("lifecycle_receipt")
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("schema") != RETRY_LIFECYCLE_RECEIPT_SCHEMA
            or receipt.get("request_id") != payload.get("request_id")
            or not isinstance(payload.get("new_master"), Mapping)
        ):
            raise RuntimeError("completed retry lifecycle receipt is malformed")
        material = dict(receipt)
        receipt_cid = material.pop("receipt_cid", "")
        if (
            receipt_cid
            != "sha256:" + _sha256_text(_canonical_json(material))
            or receipt.get("intent_cid") != payload.get("intent_cid")
            or receipt.get("request_digest") != payload.get("request_digest")
            or receipt.get("new_master") != payload.get("new_master")
            or receipt.get("retry_reset_anchor")
            != payload.get("retry_reset_anchor")
            or receipt.get("checkout_release_receipt")
            != payload.get("checkout_release_receipt")
            or receipt.get("execution_intent_cid")
            != execution_intent.get("execution_intent_cid")
        ):
            raise RuntimeError("completed retry lifecycle receipt is not content-bound")
        reset_receipt = payload.get("retry_reset_receipt")
        assert isinstance(reset_receipt, Mapping)
        reset_material = {
            key: value for key, value in reset_receipt.items() if key != "receipt_cid"
        }
        proof_module = _accelerate_module(
            "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
            "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts",
        )
        if reset_receipt.get("receipt_cid") != proof_module.content_identity(
            reset_material
        ):
            raise RuntimeError("completed nested retry-reset receipt is not content-bound")
        _verify_retry_checkout_release(payload)
    return payload


def _identity_is_live(identity: Mapping[str, Any]) -> bool:
    pid = _safe_int(identity.get("pid"))
    actual = _process_birth_identity(pid)
    return bool(
        actual
        and all(
            actual.get(key) == identity.get(key)
            for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
        )
    )


def _process_parent_pid(pid: int) -> int | None:
    try:
        tail = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(
            ") ", 1
        )[1].split()
        parent = int(tail[1])
    except (OSError, IndexError, ValueError):
        return None
    return parent if parent > 0 else None


def _process_session_id(pid: int) -> int | None:
    try:
        tail = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(
            ") ", 1
        )[1].split()
        session_id = int(tail[3])
    except (OSError, IndexError, ValueError):
        return None
    return session_id if session_id > 0 else None


def _process_session_members(session_id: int) -> tuple[int, ...]:
    """Return the bounded live membership of one positive process session."""

    if session_id <= 0:
        raise RuntimeError("process session identity must be positive")
    members: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _process_session_id(pid) == session_id:
            members.append(pid)
    return tuple(sorted(members))


def _capture_process_tree(root_pid: int) -> tuple[dict[str, Any], ...]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        parent = _process_parent_pid(pid)
        if parent is not None:
            parents[pid] = parent
    members = {root_pid}
    changed = True
    while changed:
        before = len(members)
        members.update(pid for pid, parent in parents.items() if parent in members)
        changed = len(members) != before
    identities = []
    for pid in (root_pid, *sorted(members.difference({root_pid}))):
        identity = _process_birth_identity(pid)
        if identity is not None:
            identities.append(identity)
    if not identities or _safe_int(identities[0].get("pid")) != root_pid:
        raise RuntimeError("cannot capture the exact master process tree")
    return tuple(identities)


def _current_owner_identity() -> dict[str, Any]:
    identity = _process_birth_identity(os.getpid())
    if identity is None:
        raise RuntimeError("cannot bind retry lifecycle owner process birth")
    return identity


def _retry_reset_module() -> Any:
    return _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.duckdb_retry_reset",
        "ipfs_accelerate_py.agent_supervisor.duckdb_retry_reset",
    )


def _decode_retry_lifecycle_request_file(
    request_file: Path,
) -> tuple[Any, bytes]:
    control_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.control_contracts",
        "ipfs_accelerate_py.agent_supervisor.control_contracts",
    )
    request_payload, request_file_bytes = _strict_json_file(
        request_file,
        noun="retry lifecycle OperationRequest",
    )
    request = control_module.decode_operation_request(request_payload)
    if request.operation.value != "retry" or request.dry_run:
        raise RuntimeError("recover-task requires a real Operation.RETRY request")
    if request.repository_root != str(REPO_ROOT.resolve()):
        raise RuntimeError("retry request repository_root is not this checkout")
    if request.state_root != str(RUNTIME_ROOT.resolve()):
        raise RuntimeError("retry request state_root must be the complete RUNTIME_ROOT")
    return request, request_file_bytes


def _historical_completed_retry_lifecycle_receipt(
    request: Any,
    journal: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify a completed receipt without consulting mutable current state."""

    if journal.get("phase") != "completed":
        raise RuntimeError("retry lifecycle is not historically complete")
    module = _retry_reset_module()
    binding = module._binding_from_parameters(request.parameters)
    task = journal.get("task")
    writer = journal.get("writer")
    authorization = journal.get("authorization")
    retry_receipt = journal.get("retry_reset_receipt")
    lifecycle_receipt = journal.get("lifecycle_receipt")
    execution_intent = _retry_execution_intent_binding_record(journal)
    if (
        journal.get("request_id") != request.request_id
        or journal.get("request_digest") != _retry_lifecycle_request_digest(request)
        or journal.get("repository_root") != request.repository_root
        or journal.get("runtime_root") != request.state_root
        or journal.get("database_path")
        != str((Path(request.state_root) / binding.database_path).resolve())
        or journal.get("plan_root_cid") != binding.plan_root_cid
        or journal.get("task_source_repository_tree_id")
        != binding.task_source_repository_tree_id
        or journal.get("repository_head_commit") != binding.repository_head_commit
        or journal.get("repository_head_tree") != request.tree_id
        or task
        != {
            "task_cid": binding.task_cid,
            "task_alias": binding.task_alias,
            "status": binding.expected_status,
            "revision": binding.task_revision,
        }
        or writer
        != {
            "writer_id": binding.writer_id,
            "fencing_token": binding.writer_fencing_token,
        }
        or not isinstance(authorization, Mapping)
        or authorization.get("decision_id")
        != request.authorization.decision_id
        or not isinstance(retry_receipt, Mapping)
        or retry_receipt.get("schema") != module.RETRY_RESET_RECEIPT_SCHEMA
        or retry_receipt.get("request_id") != request.request_id
        or retry_receipt.get("task_cid") != binding.task_cid
        or retry_receipt.get("task_alias") != binding.task_alias
        or retry_receipt.get("writer_id") != binding.writer_id
        or retry_receipt.get("writer_fencing_token")
        != binding.writer_fencing_token
        or retry_receipt.get("execution_intent_cid")
        != execution_intent.get("execution_intent_cid")
        or not isinstance(lifecycle_receipt, Mapping)
        or lifecycle_receipt.get("retry_reset_receipt_cid")
        != retry_receipt.get("receipt_cid")
        or lifecycle_receipt.get("execution_intent_cid")
        != execution_intent.get("execution_intent_cid")
    ):
        raise RuntimeError("historical retry lifecycle/request binding is invalid")
    _verify_parent_retry_reset_anchor(journal, request=request)
    _verify_retry_checkout_release(journal)
    return dict(lifecycle_receipt)


def _retry_lifecycle_authority(
    request_file: Path,
    *,
    require_original_task: bool,
    require_live_master: bool,
    require_fresh_permit: bool,
) -> dict[str, Any]:
    """Decode and independently bind one pre-authorized reset request."""

    module = _retry_reset_module()
    authorization_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.authorization_logic",
        "ipfs_accelerate_py.agent_supervisor.authorization_logic",
    )
    checkout_module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.merge.checkout_lock",
        "ipfs_accelerate_py.agent_supervisor.checkout_lock",
    )
    request, request_file_bytes = _decode_retry_lifecycle_request_file(request_file)
    runtime_root = RUNTIME_ROOT.resolve()
    if checkout_module.checkout_repository_id(REPO_ROOT.resolve()) != request.repository_id:
        raise RuntimeError("retry request repository_id is stale")
    if _git("branch", "--show-current") != TARGET_BRANCH:
        raise RuntimeError("retry lifecycle requires the canonical target branch")
    dirty = _git("status", "--porcelain=v1")
    if dirty:
        raise RuntimeError("retry lifecycle requires a clean target worktree")
    if _git("-C", "ipfs_accelerate_py", "status", "--porcelain=v1"):
        raise RuntimeError("retry lifecycle requires a clean accelerator submodule")
    if _head_gitlink_commit("ipfs_accelerate_py") != _git(
        "-C", "ipfs_accelerate_py", "rev-parse", "HEAD"
    ):
        raise RuntimeError("retry lifecycle accelerator checkout/gitlink differ")

    binding = module._binding_from_parameters(request.parameters)
    if binding.database_path != "control.duckdb":
        raise RuntimeError("retry request does not bind the canonical control database")
    if (runtime_root / binding.database_path).resolve() != DATABASE_PATH.resolve():
        raise RuntimeError("retry request database path does not match DATABASE_PATH")
    if binding.lifecycle_owner_paths != ("master/supervisor.pid",):
        raise RuntimeError("retry request must bind the one canonical master PID path")

    owner = module._load_owner_config(runtime_root)
    module._assert_owner_binding(request, binding, owner)
    if owner.repository_root != str(REPO_ROOT.resolve()):
        raise RuntimeError("retry-reset owner repository binding is stale")
    owner_path = runtime_root / module.RETRY_RESET_OWNER_FILE
    owner_bytes = _strict_regular_bytes(
        owner_path,
        noun="retry-reset owner configuration",
    )
    policy_path = module._resolve_under(runtime_root, owner.policy_path)
    policy = module._load_policy(policy_path, expected_digest=owner.policy_digest)
    registered = {
        item.decision_id: item for item in policy.permits
    }.get(request.authorization.decision_id if request.authorization else "")
    if registered is None or registered != request.authorization:
        raise RuntimeError("retry permit was not issued by the pinned owner policy")
    if require_fresh_permit:
        authorization_module.ControlMutationAuthorizer(policy).validate(request)

    expected_effect = module.retry_reset_expected_effect(
        repository_root=request.repository_root,
        state_root=request.state_root,
        repository_id=request.repository_id,
        tree_id=request.tree_id,
        parameters=request.parameters,
    )
    if request.expected_effects != (expected_effect,):
        raise RuntimeError("retry request has a non-canonical expected effect")
    if request.fencing_epoch != binding.writer_fencing_token:
        raise RuntimeError("retry request and DuckDB writer fences differ")

    head_commit = _git("rev-parse", "--verify", "HEAD")
    head_tree = _git("rev-parse", "--verify", "HEAD^{tree}")
    if (
        head_commit != binding.repository_head_commit
        or head_tree != request.tree_id
    ):
        raise RuntimeError("retry request does not bind the current Git HEAD/tree")

    source = _source()
    snapshot = source.snapshot()
    (
        _retry_launch_snapshot,
        _retry_execution_slice,
        _retry_execution_slice_digest,
        bootstrap_completion_evidence_id,
    ) = _task_source_launch_contract(source)
    if (
        snapshot.plan_root_cid != binding.plan_root_cid
        or snapshot.repository_tree_id
        != binding.task_source_repository_tree_id
        or owner.task_source_repository_tree_id != snapshot.repository_tree_id
    ):
        raise RuntimeError("retry request does not bind the current DuckDB plan/tree")
    writer = source.current_writer_fence()
    if (writer.writer_id, writer.fencing_token) != (
        binding.writer_id,
        binding.writer_fencing_token,
    ):
        raise RuntimeError("retry request DuckDB writer identity/fence is stale")
    task = source.get_task(binding.task_cid)
    if task is None or task.task_alias != binding.task_alias:
        raise RuntimeError("retry request task CID/alias does not resolve exactly")
    if require_original_task and (
        task.revision != binding.task_revision
        or task.status != binding.expected_status
    ):
        raise RuntimeError("retry request task status/revision is stale")

    environment_probe = _run_environment_probe(_environment_python())
    environment_receipt, environment_receipt_bytes = _strict_json_file(
        ENVIRONMENT_RECEIPT,
        noun="sealed execution-environment receipt",
    )
    environment_valid, environment_detail = _validate_environment_receipt(
        environment_receipt,
        environment_probe,
    )
    if not environment_valid:
        raise RuntimeError(
            "retry lifecycle sealed environment is invalid: " + environment_detail
        )

    stored_master, _stored_bytes = _strict_json_file(
        MASTER_IDENTITY,
        noun="stored master process-birth identity",
    )
    expected_master_fields = {
        "schema": "ipfs_datasets_py/duckdb-quack-master-identity@3",
        "program_id": PROGRAM_ID,
        "repository_root": str(REPO_ROOT.resolve()),
        "master_root": str(MASTER_ROOT.resolve()),
        "master_pid_path": str(MASTER_PID.resolve()),
        "plan_root_cid": snapshot.plan_root_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "bootstrap_completion_evidence_id": bootstrap_completion_evidence_id,
    }
    if any(stored_master.get(key) != value for key, value in expected_master_fields.items()):
        raise RuntimeError("stored master identity has stale program/plan bindings")
    master_pid = _safe_int(stored_master.get("pid"))
    lane_count = _safe_int(stored_master.get("lane_count"))
    if not 1 <= lane_count <= MAX_IMPLEMENTATION_LANES:
        raise RuntimeError("stored master lane count is invalid")
    pidfile_pid = _read_pid(MASTER_PID)
    if pidfile_pid not in {None, master_pid}:
        raise RuntimeError("master PID file conflicts with its process-birth receipt")

    expected_lanes = tuple(
        module.LaneBinding(
            "dqk",
            f"state/lane-{index}/dqk_task_state.json",
            f"state/lane-{index}/task_queue.json",
        )
        for index in range(lane_count)
    )
    if binding.lanes != expected_lanes or owner.lanes != expected_lanes:
        raise RuntimeError("retry request does not bind every canonical lane exactly")

    actual_master = _process_birth_identity(master_pid)
    if actual_master is not None:
        bound, reason = _master_process_status(
            master_pid,
            expected_plan_root=snapshot.plan_root_cid,
            expected_repository_root=snapshot.repository_tree_id,
        )
        if not bound:
            raise RuntimeError(f"live master is not identity-bound: {reason}")
    elif require_live_master:
        raise RuntimeError("the initial retry lifecycle owner requires a live bound master")

    checkout_binding = _retry_checkout_snapshot()
    parent_checkout = next(
        item for item in checkout_binding if item["role"] == "parent"
    )
    if (
        parent_checkout["repository_id"] != request.repository_id
        or parent_checkout["head_commit"] != head_commit
        or parent_checkout["head_tree"] != head_tree
    ):
        raise RuntimeError("retry checkout binding changed during authority admission")

    return {
        "module": module,
        "request": request,
        "request_file_bytes": request_file_bytes,
        "request_file_digest": (
            f"sha256:{hashlib.sha256(request_file_bytes).hexdigest()}"
        ),
        "binding": binding,
        "owner": owner,
        "owner_digest": f"sha256:{hashlib.sha256(owner_bytes).hexdigest()}",
        "policy": policy,
        "policy_path": policy_path,
        "source": source,
        "snapshot": snapshot,
        "task": task,
        "writer": writer,
        "stored_master": stored_master,
        "actual_master": actual_master,
        "lane_count": lane_count,
        "head_commit": head_commit,
        "head_tree": head_tree,
        "checkout_binding": checkout_binding,
        "environment_evidence": {
            "receipt_path": str(ENVIRONMENT_RECEIPT.resolve()),
            "receipt_sha256": (
                f"sha256:{hashlib.sha256(environment_receipt_bytes).hexdigest()}"
            ),
            "receipt_id": environment_receipt["receipt_id"],
            "environment_root": environment_probe["environment_root"],
            "sealed_python_launcher_path": environment_probe[
                "sealed_python_launcher_path"
            ],
            "sealed_python_launcher_sha256": environment_probe[
                "sealed_python_launcher_sha256"
            ],
            "base_python_sha256": environment_probe["base_python_sha256"],
            "site_packages_manifest_sha256": environment_probe[
                "site_packages_manifest_sha256"
            ],
            "duckdb_version": environment_probe["duckdb_version"],
            "duckdb_record_evidence_sha256": environment_probe[
                "duckdb_record_evidence_sha256"
            ],
        },
    }


def _retry_lifecycle_owner_record(
    identity: Mapping[str, Any], *, adopted_at: str | None = None
) -> dict[str, Any]:
    return {
        "adopted_at": adopted_at or datetime.now(timezone.utc).isoformat(),
        **{
            key: identity.get(key)
            for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256", "argv")
        },
    }


def _assert_retry_lifecycle_context(
    context: Mapping[str, Any],
    journal: Mapping[str, Any],
) -> None:
    request = context["request"]
    binding = context["binding"]
    owner = context["owner"]
    policy = context["policy"]
    task_binding = journal.get("task")
    writer_binding = journal.get("writer")
    owner_binding = journal.get("owner_configuration")
    policy_binding = journal.get("policy")
    authorization_binding = journal.get("authorization")
    expected = {
        "request_id": request.request_id,
        "request_digest": _retry_lifecycle_request_digest(request),
        "request_file_digest": context["request_file_digest"],
        "repository_root": str(REPO_ROOT.resolve()),
        "runtime_root": str(RUNTIME_ROOT.resolve()),
        "database_path": str(DATABASE_PATH.resolve()),
        "plan_root_cid": context["snapshot"].plan_root_cid,
        "task_source_repository_tree_id": context["snapshot"].repository_tree_id,
        "repository_head_commit": context["head_commit"],
        "repository_head_tree": context["head_tree"],
        "checkout_binding": context["checkout_binding"],
    }
    if any(journal.get(key) != value for key, value in expected.items()):
        raise RuntimeError("retry lifecycle journal no longer matches current authority")
    _retry_execution_intent_binding_record(journal)
    if task_binding != {
        "task_cid": binding.task_cid,
        "task_alias": binding.task_alias,
        "status": binding.expected_status,
        "revision": binding.task_revision,
    }:
        raise RuntimeError("retry lifecycle journal task binding changed")
    if writer_binding != {
        "writer_id": binding.writer_id,
        "fencing_token": binding.writer_fencing_token,
    }:
        raise RuntimeError("retry lifecycle journal writer binding changed")
    if (
        not isinstance(owner_binding, Mapping)
        or owner_binding.get("digest") != context["owner_digest"]
        or owner_binding.get("payload") != owner.to_dict()
        or not isinstance(policy_binding, Mapping)
        or policy_binding.get("path") != str(context["policy_path"])
        or policy_binding.get("digest") != owner.policy_digest
        or policy_binding.get("policy_id") != policy.policy_id
        or policy_binding.get("policy_revision") != policy.policy_revision
        or policy_binding.get("authorization_decision_id")
        != request.authorization.decision_id
        or authorization_binding
        != {
            "decision_id": request.authorization.decision_id,
            "evaluated_at_ms": request.authorization.evaluated_at_ms,
            "expires_at_ms": request.authorization.expires_at_ms,
            "lease_id": request.lease_id,
            "fencing_epoch": request.fencing_epoch,
        }
        or journal.get("environment") != context["environment_evidence"]
    ):
        raise RuntimeError(
            "retry lifecycle owner/policy/environment trust anchor changed"
        )


def _adopt_retry_lifecycle_journal(
    journal: dict[str, Any],
    *,
    path: Path,
) -> dict[str, Any]:
    current = _current_owner_identity()
    owners = list(journal["lifecycle_owners"])
    previous = owners[-1]
    same_owner = all(
        previous.get(key) == current.get(key)
        for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
    )
    if not same_owner and _identity_is_live(previous):
        raise RuntimeError("another identity-bound lifecycle owner is still live")
    if not same_owner:
        owners.append(_retry_lifecycle_owner_record(current))
        if len(owners) > 32:
            raise RuntimeError("retry lifecycle recovery-owner bound is exhausted")
        journal["lifecycle_owners"] = owners
        journal["updated_at"] = datetime.now(timezone.utc).isoformat()
        _durable_retry_lifecycle_write(path, journal)
    return journal


@contextmanager
def _retry_lifecycle_lock_context() -> Iterable[None]:
    """Lock the declared reset lifecycle path without following a symlink."""

    import fcntl
    import stat

    _journal_root, lock_path = _retry_lifecycle_paths()
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError("retry lifecycle lock is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise RuntimeError("retry lifecycle lock is not owner-controlled")
        deadline = time.monotonic() + 30.0
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out acquiring retry lifecycle lock")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _declared_retry_owner_pids(context: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    module = context["module"]
    binding = context["binding"]
    paths = set(binding.lifecycle_owner_paths)
    for lane in binding.lanes:
        paths.update(
            {
                lane.supervisor_pid_path,
                lane.daemon_pid_path,
                lane.status_path,
            }
        )
    result: dict[str, tuple[int, ...]] = {}
    for relative in sorted(paths):
        pids = tuple(module._live_pids(module._resolve_under(RUNTIME_ROOT, relative)))
        if pids:
            result[relative] = pids
    return result


def _new_retry_lifecycle_journal(context: Mapping[str, Any]) -> dict[str, Any]:
    request = context["request"]
    actual_master = context.get("actual_master")
    if not isinstance(actual_master, Mapping):
        raise RuntimeError("a new retry lifecycle requires a live bound master")
    master_pid = _safe_int(actual_master.get("pid"))
    master_session_id = _process_session_id(master_pid)
    if master_pid <= 0 or master_session_id != master_pid:
        raise RuntimeError(
            "retry lifecycle requires a dedicated-session master; "
            "foreground or ambiguously owned process trees cannot be drained"
        )
    process_tree = _capture_process_tree(master_pid)
    tree_pids = {_safe_int(item.get("pid")) for item in process_tree}
    owner_identity = _current_owner_identity()
    if _safe_int(owner_identity.get("pid")) in tree_pids:
        raise RuntimeError("retry lifecycle owner must run outside the drained process tree")
    declared = _declared_retry_owner_pids(context)
    undeclared_tree = {
        pid
        for pids in declared.values()
        for pid in pids
        if pid not in tree_pids
    }
    if undeclared_tree:
        raise RuntimeError(
            "declared lane/provider owner is outside the bound master tree: "
            + ", ".join(str(pid) for pid in sorted(undeclared_tree))
        )
    argv = tuple(str(item) for item in actual_master.get("argv") or ())
    duration_text = _option_value(argv, "--duration-seconds")
    try:
        duration = float(duration_text)
    except ValueError as exc:
        raise RuntimeError("bound master duration is malformed") from exc
    if not duration > 0:
        raise RuntimeError("bound master duration is not positive")
    execution_slice = _master_execution_slice(argv)
    task = context["task"]
    writer = context["writer"]
    owner = context["owner"]
    policy = context["policy"]
    prepared_at = datetime.now(timezone.utc).isoformat()
    journal: dict[str, Any] = {
        "schema": RETRY_LIFECYCLE_SCHEMA,
        "program_id": PROGRAM_ID,
        "phase": "prepared",
        "request_id": request.request_id,
        "request_digest": _retry_lifecycle_request_digest(request),
        "request_file_digest": context["request_file_digest"],
        "repository_root": str(REPO_ROOT.resolve()),
        "runtime_root": str(RUNTIME_ROOT.resolve()),
        "database_path": str(DATABASE_PATH.resolve()),
        "plan_root_cid": context["snapshot"].plan_root_cid,
        "task_source_repository_tree_id": context["snapshot"].repository_tree_id,
        "repository_head_commit": context["head_commit"],
        "repository_head_tree": context["head_tree"],
        "checkout_binding": [
            dict(item) for item in context["checkout_binding"]
        ],
        "task": {
            "task_cid": task.task_cid,
            "task_alias": task.task_alias,
            "status": task.status,
            "revision": task.revision,
        },
        "writer": {
            "writer_id": writer.writer_id,
            "fencing_token": writer.fencing_token,
        },
        "owner_configuration": {
            "path": str(
                RUNTIME_ROOT.resolve() / context["module"].RETRY_RESET_OWNER_FILE
            ),
            "digest": context["owner_digest"],
            "payload": owner.to_dict(),
        },
        "policy": {
            "path": str(context["policy_path"]),
            "digest": owner.policy_digest,
            "policy_id": policy.policy_id,
            "policy_revision": policy.policy_revision,
            "authorization_decision_id": request.authorization.decision_id,
        },
        "authorization": {
            "decision_id": request.authorization.decision_id,
            "evaluated_at_ms": request.authorization.evaluated_at_ms,
            "expires_at_ms": request.authorization.expires_at_ms,
            "lease_id": request.lease_id,
            "fencing_epoch": request.fencing_epoch,
        },
        "environment": dict(context["environment_evidence"]),
        "old_master": {
            "stored": dict(context["stored_master"]),
            "actual": dict(actual_master),
            "lane_count": context["lane_count"],
            "duration_seconds": duration_text,
            "execution_slice": list(execution_slice),
            "dedicated_session_id": master_session_id,
        },
        "old_process_tree": [dict(item) for item in process_tree],
        "lifecycle_owners": [
            _retry_lifecycle_owner_record(
                owner_identity, adopted_at=prepared_at
            )
        ],
        "created_at": prepared_at,
        "updated_at": prepared_at,
    }
    journal["intent_cid"] = _retry_lifecycle_intent_cid(journal)
    return journal


def _retry_parent_from_execution_projection(
    context: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    module = context["module"]
    prepared = projection.get("parent_prepared")
    if not isinstance(prepared, Mapping):
        raise RuntimeError("retry execution intent lacks parent PREPARED material")
    journal = dict(prepared)
    journal["execution_intent"] = module.retry_reset_execution_intent_binding(
        projection
    )
    _retry_execution_intent_binding_record(journal)
    return journal


def _assert_retry_parent_descends_from_prepared(
    journal: Mapping[str, Any],
    prepared: Mapping[str, Any],
) -> None:
    """Reject a hand-authored parent before it can reach the signal boundary."""

    immutable = {
        key: value
        for key, value in prepared.items()
        if key not in {"phase", "updated_at", "lifecycle_owners"}
    }
    prepared_owners = prepared.get("lifecycle_owners")
    current_owners = journal.get("lifecycle_owners")
    if (
        any(journal.get(key) != value for key, value in immutable.items())
        or not isinstance(prepared_owners, list)
        or not isinstance(current_owners, list)
        or current_owners[: len(prepared_owners)] != prepared_owners
    ):
        raise RuntimeError(
            "retry parent journal does not descend from its durable PREPARED event"
        )


def _prepare_or_recover_retry_parent(
    request_file: Path,
    context: Mapping[str, Any],
    *,
    path: Path,
    fault_injector: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Publish DB authority before exposing any signal-capable parent journal."""

    module = context["module"]
    projection = module.recover_duckdb_retry_reset_execution_intent(
        context["request"],
        trusted_policy=context["policy"],
        trusted_owner=context["owner"],
        expected_parent_journal_path=path,
    )
    selected_context = dict(context)
    if projection is None:
        # Re-run every mutable check before constructing the exact PREPARED
        # material.  The released prepare API repeats those reads at the
        # writer-fenced DuckDB append boundary.
        selected_context = _retry_lifecycle_authority(
            request_file,
            require_original_task=True,
            require_live_master=True,
            require_fresh_permit=True,
        )
        prepared = _new_retry_lifecycle_journal(selected_context)
        try:
            projection = module.prepare_duckdb_retry_reset_execution_intent(
                selected_context["request"],
                trusted_policy=selected_context["policy"],
                trusted_owner=selected_context["owner"],
                parent_prepared=prepared,
                parent_journal_path=path,
                request_file_bytes=selected_context["request_file_bytes"],
                fault_injector=fault_injector,
            )
        except module.DuckDBRetryResetConflict:
            # Another owner may have won the same request race with its own
            # exact PREPARED timestamp/process owner.  Only the durable event,
            # never our losing in-memory candidate, can be adopted.
            projection = module.recover_duckdb_retry_reset_execution_intent(
                selected_context["request"],
                trusted_policy=selected_context["policy"],
                trusted_owner=selected_context["owner"],
                expected_parent_journal_path=path,
            )
            if projection is None:
                raise
    journal = _retry_parent_from_execution_projection(
        selected_context, projection
    )
    if fault_injector:
        fault_injector("execution_intent_prepared")
    return selected_context, journal


def _assert_retry_runtime_quiescent(
    context: Mapping[str, Any],
    journal: Mapping[str, Any],
) -> None:
    module = context["module"]
    binding = context["binding"]
    _assert_captured_retry_tree_dead(journal)
    lane_states = {
        lane.state_path: module._strict_state(
            module._resolve_under(RUNTIME_ROOT, lane.state_path)
        )
        for lane in binding.lanes
    }
    for lane in binding.lanes:
        module._strict_queue(module._resolve_under(RUNTIME_ROOT, lane.queue_path))
    module._assert_quiescent(RUNTIME_ROOT, binding, lane_states)
    module._assert_no_undeclared_matching_lanes(RUNTIME_ROOT, binding)


def _assert_captured_retry_tree_dead(journal: Mapping[str, Any]) -> None:
    captured = list(journal.get("old_process_tree") or ()) + list(
        journal.get("drain_process_tree") or ()
    )
    still_live = sorted(
        {
            _safe_int(identity.get("pid"))
            for identity in captured
            if isinstance(identity, Mapping) and _identity_is_live(identity)
        }
    )
    if still_live:
        raise RuntimeError(
            "drained master process tree is still live: "
            + ", ".join(str(pid) for pid in still_live)
        )
    session_id = _safe_int(
        (journal.get("old_master") or {}).get("dedicated_session_id")
        if isinstance(journal.get("old_master"), Mapping)
        else 0
    )
    if session_id <= 0:
        raise RuntimeError("retry lifecycle lacks a dedicated process-session binding")
    session_members = _process_session_members(session_id)
    if session_members:
        raise RuntimeError(
            "drained master session still owns live processes: "
            + ", ".join(str(pid) for pid in session_members)
        )


def _drain_retry_master(
    context: Mapping[str, Any],
    journal: dict[str, Any],
    *,
    path: Path,
    timeout_seconds: float,
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    old_identity = journal["old_master"]["actual"]
    old_pid = _safe_int(old_identity.get("pid"))
    if journal["phase"] == "prepared":
        actual = _process_birth_identity(old_pid)
        if actual is not None and not all(
            actual.get(key) == old_identity.get(key)
            for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
        ):
            raise RuntimeError("master PID was reused before governed drain")
        if actual is not None:
            refreshed = _capture_process_tree(old_pid)
            owner_pid = os.getpid()
            if any(_safe_int(item.get("pid")) == owner_pid for item in refreshed):
                raise RuntimeError("lifecycle owner entered the drained process tree")
            journal["drain_process_tree"] = [dict(item) for item in refreshed]
        else:
            journal["drain_process_tree"] = []
        journal["phase"] = "draining"
        journal["drain_started_at"] = datetime.now(timezone.utc).isoformat()
        journal["drain_cid"] = _retry_lifecycle_drain_cid(journal)
        journal["updated_at"] = journal["drain_started_at"]
        _durable_retry_lifecycle_write(path, journal)
        if fault_injector:
            fault_injector("draining")

    if journal["phase"] == "draining" and _identity_is_live(old_identity):
        # Re-read and compare all process-birth fields immediately before the
        # only signal this owner is permitted to send.
        actual = _process_birth_identity(old_pid)
        if not actual or any(
            actual.get(key) != old_identity.get(key)
            for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
        ):
            raise RuntimeError("master identity changed at the drain signal boundary")
        os.kill(old_pid, signal.SIGTERM)
        if fault_injector:
            fault_injector("drain_signalled")

    deadline = time.monotonic() + timeout_seconds
    last_error = "process tree has not quiesced"
    while time.monotonic() < deadline:
        try:
            _assert_retry_runtime_quiescent(context, journal)
            break
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.25)
    else:
        raise RuntimeError(
            "retry reset refused because quiescence is uncertain: " + last_error
        )
    journal["phase"] = "drained"
    journal["drained_at"] = datetime.now(timezone.utc).isoformat()
    journal["drained_cid"] = _retry_lifecycle_drained_cid(journal)
    journal["updated_at"] = journal["drained_at"]
    _durable_retry_lifecycle_write(path, journal)
    if fault_injector:
        fault_injector("drained")
    return journal


def _retry_reset_anchor_record(
    *,
    journal_path: Path,
    reset_journal: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    event = reset_journal.get("completion_event")
    if not isinstance(event, Mapping):
        raise RuntimeError("retry-reset completion event anchor is missing")
    anchored_event = {
        key: event.get(key) for key in ("event_cid", "sequence", "revision")
    }
    if (
        anchored_event["event_cid"] != receipt.get("receipt_cid")
        or not isinstance(anchored_event["sequence"], int)
        or isinstance(anchored_event["sequence"], bool)
        or not isinstance(anchored_event["revision"], int)
        or isinstance(anchored_event["revision"], bool)
    ):
        raise RuntimeError("retry-reset completion event anchor is malformed")
    anchor: dict[str, Any] = {
        "schema": RETRY_RESET_ANCHOR_SCHEMA,
        "journal_path": str(journal_path),
        "journal_key_cid": str(reset_journal.get("journal_key_cid") or ""),
        "request_id": str(reset_journal.get("request_id") or ""),
        "intent_cid": str(reset_journal.get("intent_cid") or ""),
        "receipt_cid": str(receipt.get("receipt_cid") or ""),
        "completion_event": anchored_event,
    }
    if any(
        not anchor[field]
        for field in ("journal_key_cid", "request_id", "intent_cid", "receipt_cid")
    ):
        raise RuntimeError("retry-reset anchor identity is incomplete")
    anchor["anchor_cid"] = _retry_reset_anchor_cid(anchor)
    return anchor


def _completed_retry_reset_evidence(
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    module = context["module"]
    request = context["request"]
    journal_path, _receipt_root = module._journal_paths(
        RUNTIME_ROOT.resolve(), request
    )
    if not journal_path.exists():
        return None
    reset_journal = module._read_bounded_json(journal_path, "retry-reset journal")
    if reset_journal.get("phase") != "completed":
        return None
    receipt = dict(
        module._verify_completed_journal(
            state_root=RUNTIME_ROOT.resolve(),
            path=journal_path,
            journal=reset_journal,
        )
    )
    return receipt, _retry_reset_anchor_record(
        journal_path=journal_path,
        reset_journal=reset_journal,
        receipt=receipt,
    )


def _completed_retry_reset_receipt(context: Mapping[str, Any]) -> dict[str, Any] | None:
    evidence = _completed_retry_reset_evidence(context)
    return None if evidence is None else evidence[0]


def _verify_parent_retry_reset_anchor(
    journal: Mapping[str, Any],
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Rederive one parent reset anchor from the released durable authority."""

    module = _retry_reset_module()
    anchor = journal.get("retry_reset_anchor")
    nested_receipt = journal.get("retry_reset_receipt")
    if not isinstance(anchor, Mapping) or not isinstance(nested_receipt, Mapping):
        raise RuntimeError("completed retry lifecycle lacks reset authority")
    root = Path(str(journal.get("runtime_root") or "")).resolve()
    if root != RUNTIME_ROOT.resolve():
        raise RuntimeError("retry-reset anchor belongs to another runtime root")
    key = str(anchor.get("journal_key_cid") or "")
    expected_root = module._resolve_under(root, "duckdb-retry-reset/journals")
    expected_path = expected_root / f"{key}.json"
    if str(anchor.get("journal_path") or "") != str(expected_path):
        raise RuntimeError("retry-reset anchor journal path is not canonical")
    if request is not None:
        request_path, _receipt_root = module._journal_paths(root, request)
        if request_path != expected_path:
            raise RuntimeError("retry-reset anchor belongs to another request")
    reset_journal = module._read_bounded_json(expected_path, "retry-reset journal")
    verified_receipt = dict(
        module._verify_completed_journal(
            state_root=root,
            path=expected_path,
            journal=reset_journal,
        )
    )
    derived_anchor = _retry_reset_anchor_record(
        journal_path=expected_path,
        reset_journal=reset_journal,
        receipt=verified_receipt,
    )
    binding = reset_journal.get("binding")
    task = journal.get("task")
    writer = journal.get("writer")
    execution_intent = _retry_execution_intent_binding_record(journal)
    if (
        dict(anchor) != derived_anchor
        or verified_receipt != dict(nested_receipt)
        or reset_journal.get("request_id") != journal.get("request_id")
        or not isinstance(binding, Mapping)
        or not isinstance(task, Mapping)
        or not isinstance(writer, Mapping)
        or binding.get("plan_root_cid") != journal.get("plan_root_cid")
        or binding.get("task_source_repository_tree_id")
        != journal.get("task_source_repository_tree_id")
        or binding.get("repository_head_commit")
        != journal.get("repository_head_commit")
        or reset_journal.get("repository_tree_id")
        != journal.get("repository_head_tree")
        or binding.get("task_cid") != task.get("task_cid")
        or binding.get("task_alias") != task.get("task_alias")
        or binding.get("task_revision") != task.get("revision")
        or binding.get("expected_status") != task.get("status")
        or binding.get("writer_id") != writer.get("writer_id")
        or binding.get("writer_fencing_token") != writer.get("fencing_token")
        or reset_journal.get("execution_intent") != execution_intent
        or verified_receipt.get("execution_intent_cid")
        != execution_intent.get("execution_intent_cid")
    ):
        raise RuntimeError("retry-reset anchor does not match its lifecycle intent")
    return verified_receipt


def _execute_retry_reset_once(
    context: Mapping[str, Any],
    journal: Mapping[str, Any],
    *,
    path: Path,
) -> dict[str, Any]:
    execution_intent = _retry_execution_intent_binding_record(journal)
    completed = _completed_retry_reset_receipt(context)
    if completed is not None:
        if completed.get("execution_intent_cid") != execution_intent.get(
            "execution_intent_cid"
        ):
            raise RuntimeError(
                "completed retry reset consumed another execution intent"
            )
        return completed
    module = context["module"]
    leases = _retry_checkout_lease_records(journal)
    assertion = {
        "schema": RETRY_CHECKOUT_EXECUTION_ASSERTION_SCHEMA,
        "parent_journal_path": str(path),
        "request_digest": journal.get("request_digest"),
        "parent_intent_cid": journal.get("intent_cid"),
        "execution_intent_cid": execution_intent.get("execution_intent_cid"),
        "checkout_lease_set_cid": journal.get("checkout_lease_set_cid"),
        "checkout_lease_cids": [
            record["lease_cid"]
            for _lock_path, record in sorted(leases.items())
        ],
    }

    def verify_checkout_assertion(record: Mapping[str, Any]) -> bool:
        if dict(record) != assertion:
            return False
        _assert_retry_checkout_leases(journal)
        _assert_retry_checkout_snapshot(journal)
        return True

    return dict(
        module.execute_duckdb_retry_reset(
            context["request"],
            trusted_policy=context["policy"],
            trusted_owner=context["owner"],
            execution_intent=execution_intent,
            parent_journal=journal,
            checkout_lease_assertion=assertion,
            checkout_lease_verifier=verify_checkout_assertion,
        )
    )


def _matching_relaunch_masters(
    command: Sequence[str],
    marker: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    matches: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        identity = _process_birth_identity(int(entry.name))
        if not _process_identity_matches_sealed_command(identity, command):
            continue
        if (
            identity.get("boot_id") != marker.get("boot_id")
            or _safe_int(identity.get("start_ticks"))
            < _safe_int(marker.get("start_ticks_floor"))
            or _process_python_environment(_safe_int(identity.get("pid")))
            != _sealed_python_environment()
        ):
            continue
        matches.append(identity)
    return tuple(sorted(matches, key=lambda item: _safe_int(item.get("pid"))))


def _live_program_master_identities() -> tuple[dict[str, Any], ...]:
    matches: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        identity = _process_birth_identity(int(entry.name))
        argv = tuple(str(item) for item in (identity or {}).get("argv") or ())
        if (
            identity is None
            or "ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner"
            not in argv
            or _option_value(argv, "--master-pid-path") != str(MASTER_PID)
            or not _actual_master_command_matches(identity)
        ):
            continue
        matches.append(identity)
    return tuple(sorted(matches, key=lambda item: _safe_int(item.get("pid"))))


def _retry_checkout_finalization_record(
    journal: Mapping[str, Any], new_master: Mapping[str, Any]
) -> dict[str, Any]:
    leases = _retry_checkout_lease_records(journal)
    record: dict[str, Any] = {
        "schema": RETRY_CHECKOUT_FINALIZATION_SCHEMA,
        "request_digest": journal.get("request_digest"),
        "intent_cid": journal.get("intent_cid"),
        "reset_commit_cid": journal.get("reset_commit_cid"),
        "relaunch_intent_cid": journal.get("relaunch_intent_cid"),
        "checkout_lease_cids": [
            lease["lease_cid"] for _path, lease in sorted(leases.items())
        ],
        "new_master": dict(new_master),
        "finalized_at": datetime.now(timezone.utc).isoformat(),
    }
    record["finalization_cid"] = _retry_checkout_finalization_cid(record)
    return record


def _retry_checkout_release_id(
    journal: Mapping[str, Any], lease: Mapping[str, Any]
) -> str:
    return "sha256:" + _sha256_text(
        _canonical_json(
            {
                "namespace": "duckdb-quack-retry-checkout-release",
                "request_digest": journal.get("request_digest"),
                "intent_cid": journal.get("intent_cid"),
                "finalization_cid": (
                    journal.get("checkout_finalization") or {}
                ).get("finalization_cid"),
                "lease_id": lease.get("lease_id"),
            }
        )
    )


def _retry_checkout_tombstone_path(lease: Mapping[str, Any]) -> Path:
    lease_id = str(lease.get("lease_id") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", lease_id):
        raise RuntimeError("retry checkout lease ID is malformed")
    lock_path = Path(str(lease.get("lock_path") or ""))
    return lock_path.with_name(
        f".{lock_path.name}.retry-release-{lease_id.removeprefix('sha256:')}.json"
    )


def _retry_checkout_release_tombstone(
    journal: Mapping[str, Any],
    lease: Mapping[str, Any],
    *,
    prepared_at: str,
) -> dict[str, Any]:
    tombstone: dict[str, Any] = {
        "schema": RETRY_CHECKOUT_RELEASE_TOMBSTONE_SCHEMA,
        "state": "prepared",
        "request_digest": journal.get("request_digest"),
        "intent_cid": journal.get("intent_cid"),
        "finalization_cid": (
            journal.get("checkout_finalization") or {}
        ).get("finalization_cid"),
        "release_id": _retry_checkout_release_id(journal, lease),
        "repository_role": lease.get("repository_role"),
        "lock_path": lease.get("lock_path"),
        "tombstone_path": str(_retry_checkout_tombstone_path(lease)),
        "lease_id": lease.get("lease_id"),
        "lease_cid": lease.get("lease_cid"),
        "lease_record_cid": lease.get("record_cid"),
        "generation": lease.get("generation"),
        "prepared_at": prepared_at,
        "released_at": "",
        "artifact_sha256": "",
    }
    tombstone["tombstone_cid"] = _retry_checkout_tombstone_cid(tombstone)
    return tombstone


def _retry_checkout_tombstone_records(
    journal: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    leases = _retry_checkout_lease_records(journal)
    raw = journal.get("checkout_release_tombstones", [])
    if not isinstance(raw, list) or len(raw) > len(leases):
        raise RuntimeError("retry checkout release tombstones are malformed")
    result: dict[str, dict[str, Any]] = {}
    allowed = {
        "schema",
        "state",
        "request_digest",
        "intent_cid",
        "finalization_cid",
        "release_id",
        "repository_role",
        "lock_path",
        "tombstone_path",
        "lease_id",
        "lease_cid",
        "lease_record_cid",
        "generation",
        "prepared_at",
        "released_at",
        "artifact_sha256",
        "tombstone_cid",
    }
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != allowed:
            raise RuntimeError("retry checkout release tombstone is malformed")
        lock_text = str(item.get("lock_path") or "")
        lease = leases.get(lock_text)
        if (
            lease is None
            or lock_text in result
            or item.get("schema") != RETRY_CHECKOUT_RELEASE_TOMBSTONE_SCHEMA
            or item.get("state") not in {"prepared", "released"}
            or item.get("request_digest") != journal.get("request_digest")
            or item.get("intent_cid") != journal.get("intent_cid")
            or item.get("finalization_cid")
            != (journal.get("checkout_finalization") or {}).get(
                "finalization_cid"
            )
            or item.get("release_id")
            != _retry_checkout_release_id(journal, lease)
            or item.get("repository_role") != lease.get("repository_role")
            or item.get("tombstone_path")
            != str(_retry_checkout_tombstone_path(lease))
            or item.get("lease_id") != lease.get("lease_id")
            or item.get("lease_cid") != lease.get("lease_cid")
            or item.get("lease_record_cid") != lease.get("record_cid")
            or item.get("generation") != lease.get("generation")
            or not item.get("prepared_at")
            or item.get("tombstone_cid")
            != _retry_checkout_tombstone_cid(item)
        ):
            raise RuntimeError("retry checkout release tombstone is not content-bound")
        if item["state"] == "prepared" and (
            item.get("released_at") or item.get("artifact_sha256")
        ):
            raise RuntimeError("prepared checkout tombstone claims release evidence")
        if item["state"] == "released" and (
            not item.get("released_at")
            or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(item.get("artifact_sha256") or "")
            )
        ):
            raise RuntimeError("released checkout tombstone lacks artifact evidence")
        result[lock_text] = dict(item)
    if [str(item.get("lock_path") or "") for item in raw] != sorted(result):
        raise RuntimeError("retry checkout release tombstones are not ordered")
    return result


def _retry_checkout_release_receipt(
    journal: Mapping[str, Any], tombstones: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": RETRY_CHECKOUT_RELEASE_RECEIPT_SCHEMA,
        "program_id": PROGRAM_ID,
        "request_id": journal.get("request_id"),
        "request_digest": journal.get("request_digest"),
        "intent_cid": journal.get("intent_cid"),
        "finalization_cid": (
            journal.get("checkout_finalization") or {}
        ).get("finalization_cid"),
        "released_tombstones": [
            dict(item) for _path, item in sorted(tombstones.items())
        ],
        "released_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt["receipt_cid"] = _retry_checkout_release_receipt_cid(receipt)
    return receipt


def _durable_retry_checkout_release_artifact(
    journal: dict[str, Any],
    *,
    lifecycle_path: Path,
    lock_text: str,
    fault_injector: Any | None,
) -> None:
    """Atomically rename one exact lease into its durable release artifact."""

    checkout_module = _retry_checkout_module()
    leases = _retry_checkout_lease_records(journal)
    tombstones = _retry_checkout_tombstone_records(journal)
    lease = leases[lock_text]
    tombstone = tombstones[lock_text]
    lock_path = Path(lock_text)
    tombstone_path = Path(str(tombstone["tombstone_path"]))
    current = _current_owner_identity()
    binding = _retry_checkout_binding_by_path(journal)[lock_text]
    _assert_retry_checkout_lock_authority(
        binding, lock_path, require_guard=False
    )
    with checkout_module.serialized_lock_update(lock_path):
        _assert_retry_checkout_lock_authority(binding, lock_path)
        lock_exists = lock_path.exists() or lock_path.is_symlink()
        tombstone_exists = tombstone_path.exists() or tombstone_path.is_symlink()
        if tombstone_exists:
            artifact = _read_retry_checkout_lock(tombstone_path)
            artifact = _validate_retry_checkout_lease(
                artifact,
                journal=journal,
                binding=binding,
            )
            if artifact != lease:
                raise RuntimeError(
                    "retry checkout release artifact differs from its journal"
            )
            if lock_exists:
                current_lock = _read_owner_controlled_checkout_json(
                    lock_path, noun="current checkout mutation lock"
                )
                lock_metadata = lock_path.lstat()
                tombstone_metadata = tombstone_path.lstat()
                if (
                    current_lock == lease
                    and (lock_metadata.st_dev, lock_metadata.st_ino)
                    == (tombstone_metadata.st_dev, tombstone_metadata.st_ino)
                ):
                    os.unlink(lock_path)
                    directory_fd = os.open(lock_path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                    if fault_injector:
                        fault_injector(
                            "checkout_lease_unlinked:"
                            + str(lease["repository_role"])
                        )
                elif current_lock.get("lease_id") == lease.get("lease_id"):
                    raise RuntimeError(
                        "released retry checkout lease was duplicated at its lock path"
                    )
        elif lock_exists:
            stored = _read_retry_checkout_lock(lock_path)
            stored = _validate_retry_checkout_lease(
                stored,
                journal=journal,
                binding=binding,
            )
            if stored != lease:
                stored = _reconcile_retry_checkout_lease_record(
                    lease, stored, current
                )
            adopted = _adopt_retry_checkout_lease(stored, current)
            if adopted != stored:
                _replace_retry_checkout_lock(lock_path, adopted)
                if fault_injector:
                    fault_injector(
                        "checkout_release_adopted_physical:"
                        + str(lease["repository_role"])
                    )
            if adopted != lease:
                leases[lock_text] = adopted
                lease = adopted
                journal["checkout_leases"] = [
                    leases[item] for item in sorted(leases)
                ]
                replacement = _retry_checkout_release_tombstone(
                    journal,
                    lease,
                    prepared_at=str(tombstone["prepared_at"]),
                )
                tombstones[lock_text] = replacement
                journal["checkout_release_tombstones"] = [
                    tombstones[item] for item in sorted(tombstones)
                ]
                journal["updated_at"] = datetime.now(timezone.utc).isoformat()
                _durable_retry_lifecycle_write(lifecycle_path, journal)
                tombstone = replacement
            try:
                os.link(lock_path, tombstone_path, follow_symlinks=False)
            except OSError as exc:
                raise RuntimeError(
                    "retry checkout release artifact creation raced"
                ) from exc
            directory_fd = os.open(lock_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            lock_metadata = lock_path.lstat()
            tombstone_metadata = tombstone_path.lstat()
            if (lock_metadata.st_dev, lock_metadata.st_ino) != (
                tombstone_metadata.st_dev,
                tombstone_metadata.st_ino,
            ):
                raise RuntimeError(
                    "retry checkout release artifact is not the held lease inode"
                )
            if fault_injector:
                fault_injector(
                    "checkout_release_artifact_linked:"
                    + str(lease["repository_role"])
                )
            os.unlink(lock_path)
            directory_fd = os.open(lock_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            if fault_injector:
                fault_injector(
                    "checkout_lease_unlinked:" + str(lease["repository_role"])
                )
        else:
            raise RuntimeError(
                "retry checkout lease and its release artifact are both missing"
            )
    artifact_bytes = _strict_regular_bytes(
        tombstone_path,
        noun="retry checkout release artifact",
        required_mode=0o600,
        required_uid=os.geteuid(),
    )
    artifact = _strict_json_object(
        artifact_bytes.decode("utf-8"), noun="retry checkout release artifact"
    )
    if artifact != lease:
        raise RuntimeError("retry checkout release artifact changed after rename")
    if tombstone["state"] != "released":
        released = {
            **tombstone,
            "state": "released",
            "released_at": datetime.now(timezone.utc).isoformat(),
            "artifact_sha256": (
                "sha256:" + hashlib.sha256(artifact_bytes).hexdigest()
            ),
        }
        released.pop("tombstone_cid", None)
        released["tombstone_cid"] = _retry_checkout_tombstone_cid(released)
        tombstones[lock_text] = released
        journal["checkout_release_tombstones"] = [
            tombstones[item] for item in sorted(tombstones)
        ]
        journal["updated_at"] = released["released_at"]
        _durable_retry_lifecycle_write(lifecycle_path, journal)
        if fault_injector:
            fault_injector(
                "checkout_release_recorded:" + str(lease["repository_role"])
            )


def _release_retry_checkout_leases(
    journal: dict[str, Any],
    *,
    path: Path,
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    leases = _retry_checkout_lease_records(journal)
    tombstones = _retry_checkout_tombstone_records(journal)
    if not tombstones:
        prepared_at = datetime.now(timezone.utc).isoformat()
        tombstones = {
            lock_text: _retry_checkout_release_tombstone(
                journal, lease, prepared_at=prepared_at
            )
            for lock_text, lease in sorted(leases.items())
        }
        journal["checkout_release_tombstones"] = [
            tombstones[item] for item in sorted(tombstones)
        ]
        journal["updated_at"] = prepared_at
        _durable_retry_lifecycle_write(path, journal)
        if fault_injector:
            fault_injector("checkout_release_prepared")
    elif set(tombstones) != set(leases):
        raise RuntimeError("retry checkout release tombstones are incomplete")
    for lock_text in sorted(leases):
        _durable_retry_checkout_release_artifact(
            journal,
            lifecycle_path=path,
            lock_text=lock_text,
            fault_injector=fault_injector,
        )
    tombstones = _retry_checkout_tombstone_records(journal)
    if any(item["state"] != "released" for item in tombstones.values()):
        raise RuntimeError("retry checkout lease release is incomplete")
    if journal.get("checkout_release_receipt") is not None:
        return _verify_retry_checkout_release(journal)
    receipt = _retry_checkout_release_receipt(journal, tombstones)
    journal["checkout_release_receipt"] = receipt
    journal["updated_at"] = receipt["released_at"]
    _durable_retry_lifecycle_write(path, journal)
    if fault_injector:
        fault_injector("checkout_released")
    return receipt


def _verify_retry_checkout_release(journal: Mapping[str, Any]) -> dict[str, Any]:
    checkout_module = _retry_checkout_module()
    bindings = _retry_checkout_binding_by_path(journal)
    leases = _retry_checkout_lease_records(journal)
    tombstones = _retry_checkout_tombstone_records(journal)
    receipt = journal.get("checkout_release_receipt")
    if (
        set(leases) != set(bindings)
        or set(tombstones) != set(bindings)
        or any(item["state"] != "released" for item in tombstones.values())
        or not isinstance(receipt, Mapping)
        or set(receipt)
        != {
            "schema",
            "program_id",
            "request_id",
            "request_digest",
            "intent_cid",
            "finalization_cid",
            "released_tombstones",
            "released_at",
            "receipt_cid",
        }
        or receipt.get("schema") != RETRY_CHECKOUT_RELEASE_RECEIPT_SCHEMA
        or receipt.get("program_id") != PROGRAM_ID
        or receipt.get("request_id") != journal.get("request_id")
        or receipt.get("request_digest") != journal.get("request_digest")
        or receipt.get("intent_cid") != journal.get("intent_cid")
        or receipt.get("finalization_cid")
        != (journal.get("checkout_finalization") or {}).get("finalization_cid")
        or receipt.get("released_tombstones")
        != [dict(item) for _path, item in sorted(tombstones.items())]
        or not isinstance(receipt.get("released_at"), str)
        or not receipt.get("released_at")
        or receipt.get("receipt_cid")
        != _retry_checkout_release_receipt_cid(receipt)
    ):
        raise RuntimeError("retry checkout release receipt is malformed")
    for lock_text in sorted(bindings):
        lock_path = Path(lock_text)
        tombstone = tombstones[lock_text]
        artifact_path = Path(str(tombstone["tombstone_path"]))
        _assert_retry_checkout_lock_authority(
            bindings[lock_text], lock_path, require_guard=False
        )
        with checkout_module.serialized_lock_update(lock_path):
            _assert_retry_checkout_lock_authority(
                bindings[lock_text], lock_path
            )
            artifact_bytes = _strict_regular_bytes(
                artifact_path,
                noun="retry checkout release artifact",
                required_mode=0o600,
                required_uid=os.geteuid(),
            )
            artifact = _strict_json_object(
                artifact_bytes.decode("utf-8"),
                noun="retry checkout release artifact",
            )
            if (
                artifact != leases[lock_text]
                or tombstone["artifact_sha256"]
                != "sha256:" + hashlib.sha256(artifact_bytes).hexdigest()
            ):
                raise RuntimeError(
                    "retry checkout release artifact is not content-bound"
                )
            if lock_path.exists() or lock_path.is_symlink():
                current = _read_owner_controlled_checkout_json(
                    lock_path, noun="current checkout mutation lock"
                )
                if current.get("lease_id") == leases[lock_text].get("lease_id"):
                    raise RuntimeError(
                        "completed retry checkout lease remains at its lock path"
                    )
    return dict(receipt)


def _launch_or_adopt_retry_master(
    context: Mapping[str, Any],
    journal: Mapping[str, Any],
) -> dict[str, Any]:
    relaunch = journal["relaunch"]
    command = tuple(str(item) for item in relaunch["command"])
    marker = relaunch["marker"]
    snapshot = context["snapshot"]
    _assert_captured_retry_tree_dead(journal)
    candidates = _matching_relaunch_masters(command, marker)
    if len(candidates) > 1:
        raise RuntimeError("multiple exact retry-relaunch masters are live")
    candidate_ids = {
        (
            item.get("pid"),
            item.get("boot_id"),
            item.get("start_ticks"),
            item.get("cmdline_sha256"),
        )
        for item in candidates
    }
    foreign_masters = [
        item
        for item in _live_program_master_identities()
        if (
            item.get("pid"),
            item.get("boot_id"),
            item.get("start_ticks"),
            item.get("cmdline_sha256"),
        )
        not in candidate_ids
    ]
    if foreign_masters:
        raise RuntimeError("another canonical program master is already live")
    if candidates:
        pid = _safe_int(candidates[0].get("pid"))
        _bind_launched_master(
            snapshot,
            expected_command=command,
            marker=marker,
            expected_pid=pid,
        )
        return dict(_process_birth_identity(pid) or {})

    _assert_retry_runtime_quiescent(context, journal)
    pidfile_pid = _read_pid(MASTER_PID)
    if pidfile_pid is not None and _pid_exists(pidfile_pid):
        raise RuntimeError("a foreign live master occupies the canonical PID file")
    environment = _scrubbed_sealed_process_environment()
    environment.setdefault("IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER", "auto")
    MASTER_ROOT.mkdir(parents=True, exist_ok=True)
    launcher_log = MASTER_ROOT / "launcher.out"
    with launcher_log.open("ab") as output_handle:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        _bind_launched_master(
            snapshot,
            expected_command=command,
            marker=marker,
            expected_pid=process.pid,
        )
    except Exception:
        actual = _process_birth_identity(process.pid)
        if _process_identity_matches_sealed_command(actual, command):
            os.kill(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        raise
    identity = _process_birth_identity(process.pid)
    if identity is None:
        raise RuntimeError("relaunch master disappeared after identity binding")
    return identity


def _retry_lifecycle_receipt(
    context: Mapping[str, Any],
    journal: Mapping[str, Any],
    new_master: Mapping[str, Any],
) -> dict[str, Any]:
    execution_intent = _retry_execution_intent_binding_record(journal)
    receipt: dict[str, Any] = {
        "schema": RETRY_LIFECYCLE_RECEIPT_SCHEMA,
        "program_id": PROGRAM_ID,
        "request_id": context["request"].request_id,
        "request_digest": journal["request_digest"],
        "intent_cid": journal["intent_cid"],
        "plan_root_cid": context["snapshot"].plan_root_cid,
        "task_source_repository_tree_id": context["snapshot"].repository_tree_id,
        "task_cid": context["binding"].task_cid,
        "task_alias": context["binding"].task_alias,
        "execution_intent_cid": execution_intent["execution_intent_cid"],
        "retry_reset_receipt_cid": journal["retry_reset_receipt"]["receipt_cid"],
        "retry_reset_anchor": dict(journal["retry_reset_anchor"]),
        "checkout_finalization": dict(journal["checkout_finalization"]),
        "checkout_release_receipt": dict(journal["checkout_release_receipt"]),
        "old_master": journal["old_master"]["actual"],
        "new_master": dict(new_master),
        "lane_count": context["lane_count"],
        "launch_command_sha256": (
            "sha256:"
            + _sha256_text(_canonical_json(journal["relaunch"]["command"]))
        ),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt["receipt_cid"] = "sha256:" + _sha256_text(_canonical_json(receipt))
    return receipt


def _complete_retry_relaunch(
    context: Mapping[str, Any],
    journal: dict[str, Any],
    *,
    path: Path,
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    verified_reset = _completed_retry_reset_evidence(context)
    if (
        verified_reset is None
        or verified_reset[0] != journal.get("retry_reset_receipt")
        or verified_reset[1] != journal.get("retry_reset_anchor")
    ):
        raise RuntimeError("retry lifecycle reset receipt cannot be reverified")
    if journal["phase"] == "reset_committed":
        _assert_retry_checkout_leases(journal)
        _assert_retry_checkout_snapshot(journal)
        _assert_retry_runtime_quiescent(context, journal)
        launch_token = os.urandom(16).hex()
        duration_text = str(journal["old_master"]["duration_seconds"])
        duration_seconds = float(duration_text)
        command = supervisor_command(
            lanes=_safe_int(journal["old_master"]["lane_count"]),
            duration_seconds=duration_seconds,
            detach=False,
            launch_token=launch_token,
        )
        if _master_execution_slice(command) != tuple(
            journal["old_master"]["execution_slice"]
        ):
            raise RuntimeError("relaunch execution slice differs from the drained master")
        marker = _launch_marker()
        journal["relaunch"] = {
            "launch_token": launch_token,
            "duration_seconds": duration_text,
            "lane_count": context["lane_count"],
            "command": command,
            "marker": marker,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        }
        journal["phase"] = "relaunching"
        journal["relaunch_intent_cid"] = _retry_lifecycle_relaunch_intent_cid(
            journal
        )
        journal["updated_at"] = journal["relaunch"]["prepared_at"]
        _durable_retry_lifecycle_write(path, journal)
        if fault_injector:
            fault_injector("relaunching")

    if journal["phase"] == "relaunching":
        _assert_retry_checkout_leases(journal)
        if fault_injector:
            fault_injector("before_relaunch_checkout_verify")
        _assert_retry_checkout_snapshot(journal)
        relaunch = journal["relaunch"]
        launch_token = str(relaunch["launch_token"])
        duration_text = str(relaunch["duration_seconds"])
        try:
            duration_seconds = float(duration_text)
        except ValueError as exc:
            raise RuntimeError("retry relaunch duration is malformed") from exc
        expected_command = supervisor_command(
            lanes=context["lane_count"],
            duration_seconds=duration_seconds,
            detach=False,
            launch_token=launch_token,
        )
        if (
            relaunch.get("lane_count") != context["lane_count"]
            or relaunch.get("command") != expected_command
            or _master_execution_slice(expected_command)
            != tuple(journal["old_master"]["execution_slice"])
        ):
            raise RuntimeError(
                "retry relaunch command is not the canonical sealed command"
            )

        new_master = _launch_or_adopt_retry_master(context, journal)
        if fault_injector:
            fault_injector("relaunch_bound")
        bound, reason = _master_process_status(
            _safe_int(new_master.get("pid")),
            expected_plan_root=context["snapshot"].plan_root_cid,
            expected_repository_root=context["snapshot"].repository_tree_id,
        )
        if not bound:
            raise RuntimeError(
                f"relaunch master failed final identity binding: {reason}"
            )
        stored = _read_master_identity() or {}
        if _safe_int(stored.get("lane_count")) != context["lane_count"]:
            raise RuntimeError("relaunch master changed the governed lane count")
        _assert_retry_checkout_snapshot(journal)
        journal["new_master"] = dict(new_master)
        journal["checkout_finalization"] = _retry_checkout_finalization_record(
            journal, new_master
        )
        journal["phase"] = "finalizing"
        journal["updated_at"] = journal["checkout_finalization"]["finalized_at"]
        _durable_retry_lifecycle_write(path, journal)
        if fault_injector:
            fault_injector("finalizing")

    if journal["phase"] != "finalizing":
        raise RuntimeError(
            f"retry lifecycle cannot finalize from phase {journal['phase']}"
        )
    finalization = journal.get("checkout_finalization")
    if (
        not isinstance(finalization, Mapping)
        or finalization.get("finalization_cid")
        != _retry_checkout_finalization_cid(finalization)
        or finalization.get("new_master") != journal.get("new_master")
    ):
        raise RuntimeError("retry relaunch finalization is not content-bound")
    _release_retry_checkout_leases(
        journal,
        path=path,
        fault_injector=fault_injector,
    )
    receipt = _retry_lifecycle_receipt(
        context, journal, journal["new_master"]
    )
    journal["lifecycle_receipt"] = receipt
    journal["phase"] = "completed"
    journal["updated_at"] = receipt["completed_at"]
    _durable_retry_lifecycle_write(path, journal)
    _verify_retry_checkout_release(journal)
    if fault_injector:
        fault_injector("completed")
    return receipt


def _run_retry_lifecycle(
    request_file: Path,
    *,
    drain_timeout_seconds: float = 90.0,
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    """Drain, reset, and relaunch one exact pre-authorized task operation."""

    if not drain_timeout_seconds > 0 or drain_timeout_seconds == float("inf"):
        raise RuntimeError("drain timeout must be finite and positive")
    historical_request, _request_file_bytes = _decode_retry_lifecycle_request_file(
        request_file
    )
    historical_path = _retry_lifecycle_journal_path(historical_request)
    if historical_path.exists():
        with _retry_lifecycle_lock_context():
            historical = _read_retry_lifecycle_journal(
                historical_path,
                request=historical_request,
            )
            if historical["phase"] == "completed":
                return _historical_completed_retry_lifecycle_receipt(
                    historical_request,
                    historical,
                )
    # The first pass is structural and permits a completed operation to be
    # replayed after the original permit expires.  A not-yet-committed reset
    # still passes through the public executor's live-policy validation.
    context = _retry_lifecycle_authority(
        request_file,
        require_original_task=False,
        require_live_master=False,
        require_fresh_permit=False,
    )
    request = context["request"]
    path = _retry_lifecycle_journal_path(request)
    prepared_candidate: dict[str, Any] | None = None
    verified_prepared: dict[str, Any] | None = None
    if path.exists():
        with _retry_lifecycle_lock_context():
            existing = _read_retry_lifecycle_journal(path, request=request)
        if existing["phase"] in {"prepared", "draining", "drained", "leased"}:
            projection = context[
                "module"
            ].recover_duckdb_retry_reset_execution_intent(
                request,
                trusted_policy=context["policy"],
                trusted_owner=context["owner"],
                expected_parent_journal_path=path,
            )
            if projection is None:
                raise RuntimeError(
                    "retry parent journal has no durable execution-intent event"
                )
            verified_prepared = _retry_parent_from_execution_projection(
                context, projection
            )
            _assert_retry_parent_descends_from_prepared(
                existing, verified_prepared
            )
    else:
        context, prepared_candidate = _prepare_or_recover_retry_parent(
            request_file,
            context,
            path=path,
            fault_injector=fault_injector,
        )
        verified_prepared = prepared_candidate

    with _retry_lifecycle_lock_context():
        if path.exists():
            journal = _read_retry_lifecycle_journal(path, request=request)
            if journal["phase"] in {
                "prepared",
                "draining",
                "drained",
                "leased",
            }:
                if verified_prepared is None:
                    raise RuntimeError(
                        "retry parent execution intent was not verified before drain"
                    )
                _assert_retry_parent_descends_from_prepared(
                    journal, verified_prepared
                )
            _assert_retry_lifecycle_context(context, journal)
            if journal["phase"] == "completed":
                return dict(journal["lifecycle_receipt"])
            journal = _adopt_retry_lifecycle_journal(journal, path=path)
        else:
            if prepared_candidate is None:
                raise RuntimeError(
                    "retry parent journal disappeared without durable execution intent"
                )
            journal = prepared_candidate
            _assert_retry_lifecycle_context(context, journal)
            _durable_retry_lifecycle_write(path, journal)
            if fault_injector:
                fault_injector("prepared")
        if journal["phase"] in {"prepared", "draining"}:
            journal = _drain_retry_master(
                context,
                journal,
                path=path,
                timeout_seconds=drain_timeout_seconds,
                fault_injector=fault_injector,
            )
        if journal["phase"] in {
            "drained",
            "leased",
            "reset_committed",
            "relaunching",
        }:
            journal = _acquire_or_adopt_retry_checkout_leases(
                context,
                journal,
                path=path,
                fault_injector=fault_injector,
            )

    # The released executor owns its own lock at this point.  Its journal is
    # independently idempotent, so a crash after return but before the parent
    # phase update cannot apply the reset twice.
    if journal["phase"] == "leased":
        _assert_retry_checkout_leases(journal)
        if fault_injector:
            fault_injector("before_reset_checkout_verify")
        _assert_retry_checkout_snapshot(journal)
        reset_receipt = _execute_retry_reset_once(context, journal, path=path)
        reset_evidence = _completed_retry_reset_evidence(context)
        if reset_evidence is None or reset_evidence[0] != reset_receipt:
            raise RuntimeError(
                "retry reset returned without matching durable journal/event evidence"
            )
        reset_receipt, reset_anchor = reset_evidence
        if fault_injector:
            fault_injector("reset_executed")
        with _retry_lifecycle_lock_context():
            journal = _read_retry_lifecycle_journal(path, request=request)
            _assert_retry_lifecycle_context(context, journal)
            journal = _adopt_retry_lifecycle_journal(journal, path=path)
            if journal["phase"] == "leased":
                journal["retry_reset_receipt"] = reset_receipt
                journal["retry_reset_anchor"] = reset_anchor
                journal["phase"] = "reset_committed"
                journal["reset_committed_at"] = datetime.now(timezone.utc).isoformat()
                journal["reset_commit_cid"] = _retry_lifecycle_reset_commit_cid(
                    journal
                )
                journal["updated_at"] = journal["reset_committed_at"]
                _durable_retry_lifecycle_write(path, journal)
                if fault_injector:
                    fault_injector("reset_committed")

    with _retry_lifecycle_lock_context():
        journal = _read_retry_lifecycle_journal(path, request=request)
        _assert_retry_lifecycle_context(context, journal)
        if journal["phase"] == "completed":
            return dict(journal["lifecycle_receipt"])
        journal = _adopt_retry_lifecycle_journal(journal, path=path)
        if journal["phase"] == "leased":
            # A reset completed in the released journal while this owner died
            # before copying its receipt.  Recover that durable evidence and
            # never invoke a second effect.
            reset_evidence = _completed_retry_reset_evidence(context)
            if reset_evidence is None:
                raise RuntimeError("retry reset completion is uncertain; master remains stopped")
            reset_receipt, reset_anchor = reset_evidence
            journal["retry_reset_receipt"] = reset_receipt
            journal["retry_reset_anchor"] = reset_anchor
            journal["phase"] = "reset_committed"
            journal["reset_committed_at"] = datetime.now(timezone.utc).isoformat()
            journal["reset_commit_cid"] = _retry_lifecycle_reset_commit_cid(journal)
            journal["updated_at"] = journal["reset_committed_at"]
            _durable_retry_lifecycle_write(path, journal)
        if journal["phase"] not in {
            "reset_committed",
            "relaunching",
            "finalizing",
        }:
            raise RuntimeError(
                f"retry lifecycle cannot relaunch from phase {journal['phase']}"
            )
        return _complete_retry_relaunch(
            context,
            journal,
            path=path,
            fault_injector=fault_injector,
        )


def retry_lifecycle_preview(request_file: Path) -> dict[str, Any]:
    historical_request, _request_file_bytes = _decode_retry_lifecycle_request_file(
        request_file
    )
    historical_path = _retry_lifecycle_journal_path(historical_request)
    if historical_path.exists():
        historical = _read_retry_lifecycle_journal(
            historical_path,
            request=historical_request,
        )
        if historical["phase"] == "completed":
            receipt = _historical_completed_retry_lifecycle_receipt(
                historical_request,
                historical,
            )
            task = historical["task"]
            writer = historical["writer"]
            return {
                "schema": "ipfs_datasets_py/duckdb-quack-retry-lifecycle-preview@1",
                "mutated": False,
                "historical": True,
                "request_id": historical_request.request_id,
                "request_digest": historical["request_digest"],
                "runtime_root": historical["runtime_root"],
                "database_path": historical["database_path"],
                "plan_root_cid": historical["plan_root_cid"],
                "task_source_repository_tree_id": historical[
                    "task_source_repository_tree_id"
                ],
                "task_cid": task["task_cid"],
                "task_alias": task["task_alias"],
                "task_revision": task["revision"],
                "expected_status": task["status"],
                "writer_id": writer["writer_id"],
                "writer_fencing_token": writer["fencing_token"],
                "lane_count": historical["old_master"]["lane_count"],
                "lanes": historical["owner_configuration"]["payload"]["lanes"],
                "master_pid": historical["new_master"].get("pid"),
                "master_live": None,
                "journal_path": str(historical_path),
                "journal_phase": "completed",
                "lifecycle_receipt_cid": receipt["receipt_cid"],
            }
    context = _retry_lifecycle_authority(
        request_file,
        require_original_task=False,
        require_live_master=False,
        require_fresh_permit=False,
    )
    request = context["request"]
    journal_path = _retry_lifecycle_journal_path(request)
    journal = (
        _read_retry_lifecycle_journal(journal_path, request=request)
        if journal_path.exists()
        else None
    )
    recovered_event_only = False
    if journal is None:
        projection = context["module"].recover_duckdb_retry_reset_execution_intent(
            request,
            trusted_policy=context["policy"],
            trusted_owner=context["owner"],
            expected_parent_journal_path=journal_path,
            repair_projection=False,
        )
        if projection is not None:
            journal = _retry_parent_from_execution_projection(context, projection)
            recovered_event_only = True
    elif journal["phase"] in {"prepared", "draining", "drained", "leased"}:
        projection = context["module"].recover_duckdb_retry_reset_execution_intent(
            request,
            trusted_policy=context["policy"],
            trusted_owner=context["owner"],
            expected_parent_journal_path=journal_path,
            repair_projection=False,
        )
        if projection is None:
            raise RuntimeError(
                "retry parent journal has no durable execution-intent event"
            )
        prepared = _retry_parent_from_execution_projection(context, projection)
        _assert_retry_parent_descends_from_prepared(journal, prepared)
    if journal is not None:
        _assert_retry_lifecycle_context(context, journal)
        if journal["phase"] == "leased":
            _assert_retry_checkout_leases(journal)
            _assert_retry_checkout_snapshot(journal)
            _assert_retry_runtime_quiescent(context, journal)
    if journal is None:
        context = _retry_lifecycle_authority(
            request_file,
            require_original_task=True,
            require_live_master=True,
            require_fresh_permit=True,
        )
    binding = context["binding"]
    return {
        "schema": "ipfs_datasets_py/duckdb-quack-retry-lifecycle-preview@1",
        "mutated": False,
        "request_id": request.request_id,
        "request_digest": _retry_lifecycle_request_digest(request),
        "runtime_root": str(RUNTIME_ROOT.resolve()),
        "database_path": str(DATABASE_PATH.resolve()),
        "plan_root_cid": binding.plan_root_cid,
        "task_source_repository_tree_id": binding.task_source_repository_tree_id,
        "task_cid": binding.task_cid,
        "task_alias": binding.task_alias,
        "task_revision": binding.task_revision,
        "expected_status": binding.expected_status,
        "writer_id": binding.writer_id,
        "writer_fencing_token": binding.writer_fencing_token,
        "lane_count": context["lane_count"],
        "lanes": [lane.to_dict() for lane in binding.lanes],
        "master_pid": context["stored_master"].get("pid"),
        "master_live": context["actual_master"] is not None,
        "journal_path": str(journal_path),
        "journal_phase": (
            "execution_intent_prepared"
            if recovered_event_only
            else str((journal or {}).get("phase") or "absent")
        ),
    }


def _acquire_environment_lifecycle_lock(*, exclusive: bool) -> Any:
    """Acquire the owner-controlled environment lock and return its handle."""

    import fcntl
    import stat

    ENVIRONMENT_LIFECYCLE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(ENVIRONMENT_LIFECYCLE_LOCK, flags, 0o600)
    except OSError as exc:
        raise RuntimeError("environment lifecycle lock is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise RuntimeError("environment lifecycle lock is not owner-controlled")
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return os.fdopen(descriptor, "r+b", closefd=True)
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _environment_lifecycle_lock(*, exclusive: bool) -> Iterable[None]:
    handle = _acquire_environment_lifecycle_lock(exclusive=exclusive)
    try:
        yield
    finally:
        handle.close()


def _trusted_base_python_path() -> Path:
    selected = os.environ.get("IPFS_DATASETS_DQK_BASE_PYTHON", "").strip()
    raw = selected or str(getattr(sys, "_base_executable", sys.executable))
    return Path(raw).resolve(strict=True)


def _local_environment_probe(
    *,
    environment_root: str | os.PathLike[str] | None = None,
    sealed_site_roots: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Verify the installed DuckDB distribution and return bounded evidence."""

    import base64
    import csv
    import importlib.metadata
    import io
    import platform
    import stat
    import sysconfig
    import zipfile
    from pathlib import PurePosixPath
    from urllib.parse import unquote, urlparse

    prefix = Path(environment_root or sys.prefix).resolve()
    base_prefix = Path(sys.base_prefix).resolve()
    stdlib_root = Path(sysconfig.get_path("stdlib")).resolve()
    stdlib_zip = stdlib_root.parent / (
        f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    )
    dynload_root = stdlib_root / "lib-dynload"
    configured_site_roots: Sequence[str | os.PathLike[str]] = (
        tuple(sealed_site_roots)
        if sealed_site_roots is not None
        else tuple(
            value
            for value in (
                sysconfig.get_path("purelib"),
                sysconfig.get_path("platlib"),
            )
            if value
        )
    )
    site_roots = tuple(
        dict.fromkeys(Path(value).absolute() for value in configured_site_roots)
    )
    if not site_roots:
        raise RuntimeError("environment declares no site-package roots")
    for root in site_roots:
        try:
            root.resolve().relative_to(prefix)
        except ValueError as exc:
            raise RuntimeError("site-package root escapes the environment") from exc

    def base_runtime_manifest() -> tuple[str, int]:
        rows: list[dict[str, Any]] = []
        for candidate in sorted(stdlib_root.rglob("*"), key=lambda item: item.as_posix()):
            relative = candidate.relative_to(stdlib_root).as_posix()
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise RuntimeError(f"stdlib entry became unreadable: {relative}") from exc
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if stat.S_ISLNK(metadata.st_mode):
                target_text = os.readlink(candidate)
                resolved = candidate.resolve(strict=True)
                resolved_metadata = resolved.stat()
                if not stat.S_ISREG(resolved_metadata.st_mode):
                    raise RuntimeError(f"stdlib symlink is not file-bound: {relative}")
                if resolved_metadata.st_uid != 0 or resolved_metadata.st_mode & 0o022:
                    raise RuntimeError(f"stdlib symlink target is mutable: {relative}")
                rows.append(
                    {
                        "path": relative,
                        "kind": "symlink",
                        "target": target_text,
                        "resolved_path": str(resolved),
                        "sha256": _sha256_file(resolved),
                        "size": resolved_metadata.st_size,
                    }
                )
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"stdlib contains an unsupported entry: {relative}")
            if metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise RuntimeError(f"stdlib file is mutable by an untrusted principal: {relative}")
            rows.append(
                {
                    "path": relative,
                    "kind": "regular",
                    "sha256": _sha256_file(candidate),
                    "size": metadata.st_size,
                }
            )
        return f"sha256:{_sha256_text(_canonical_json(rows))}", len(rows)

    def stdlib_zip_evidence() -> tuple[bool, str]:
        """Bind the optional stdlib zip path that CPython adds before startup."""

        try:
            metadata = stdlib_zip.lstat()
        except FileNotFoundError:
            return False, ""
        except OSError as exc:
            raise RuntimeError("stdlib zip became unreadable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("stdlib zip is not a regular non-symlink file")
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RuntimeError("stdlib zip is mutable by an untrusted principal")
        return True, _sha256_file(stdlib_zip)

    def strict_path(
        candidate: Path,
        *,
        roots: Sequence[Path],
        regular_file: bool,
    ) -> Path:
        """Resolve a path only after proving every in-scope component is non-symlink."""

        absolute = candidate.absolute()
        selected_root: Path | None = None
        relative: Path | None = None
        for root in roots:
            try:
                relative = absolute.relative_to(root)
                selected_root = root
                break
            except ValueError:
                continue
        if selected_root is None or relative is None:
            raise RuntimeError(f"environment path escapes its allowed roots: {candidate}")
        try:
            root_mode = os.lstat(selected_root).st_mode
        except OSError as exc:
            raise RuntimeError(f"missing environment root: {selected_root}") from exc
        if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
            raise RuntimeError(f"environment root is not a real directory: {selected_root}")
        current = selected_root
        for part in relative.parts:
            current = current / part
            try:
                mode = os.lstat(current).st_mode
            except OSError as exc:
                raise RuntimeError(f"missing environment path: {candidate}") from exc
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"environment path contains a symlink: {candidate}")
        if regular_file:
            try:
                mode = os.lstat(absolute).st_mode
            except OSError as exc:
                raise RuntimeError(f"missing environment file: {candidate}") from exc
            if not stat.S_ISREG(mode):
                raise RuntimeError(f"environment path is not a regular file: {candidate}")
        return absolute.resolve()

    distribution = importlib.metadata.distribution("duckdb")
    raw_distribution_root = Path(distribution.locate_file(""))
    distribution_root = strict_path(
        raw_distribution_root,
        roots=site_roots,
        regular_file=False,
    )
    distribution_files = tuple(distribution.files or ())
    record_relative = next(
        (
            str(item)
            for item in distribution_files
            if str(item).endswith(".dist-info/RECORD")
        ),
        "",
    )
    if not record_relative:
        raise RuntimeError("duckdb distribution has no RECORD evidence")
    raw_record_path = Path(distribution.locate_file(record_relative))
    record_path = strict_path(
        raw_record_path,
        roots=site_roots,
        regular_file=True,
    )
    record_bytes = record_path.read_bytes()
    try:
        record_rows = tuple(
            csv.reader(io.StringIO(record_bytes.decode("utf-8", errors="strict")))
        )
    except UnicodeDecodeError as exc:
        raise RuntimeError("duckdb RECORD is not valid UTF-8") from exc

    verified: list[dict[str, Any]] = []
    unhashed: list[str] = []
    verified_paths: set[Path] = set()
    for row in record_rows:
        if len(row) != 3:
            raise RuntimeError("duckdb RECORD row must contain path, hash, and size")
        raw_path, encoded_hash, raw_size = row
        relative_path = PurePosixPath(raw_path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"unsafe duckdb RECORD path: {raw_path!r}")
        raw_installed_path = Path(distribution.locate_file(raw_path))
        installed_path = strict_path(
            raw_installed_path,
            roots=site_roots,
            regular_file=bool(encoded_hash),
        )
        try:
            installed_path.relative_to(distribution_root)
        except ValueError as exc:
            raise RuntimeError(f"duckdb RECORD path escapes its distribution: {raw_path}") from exc
        if encoded_hash:
            if not encoded_hash.startswith("sha256=") or not raw_size.isdigit():
                raise RuntimeError(f"unsupported duckdb RECORD evidence: {raw_path}")
            digest = hashlib.sha256()
            with installed_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            encoded_actual = base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")
            if encoded_actual != encoded_hash.split("=", 1)[1]:
                raise RuntimeError(f"duckdb RECORD hash mismatch: {raw_path}")
            actual_size = installed_path.stat().st_size
            if actual_size != int(raw_size):
                raise RuntimeError(f"duckdb RECORD size mismatch: {raw_path}")
            verified.append(
                {
                    "path": raw_path,
                    "sha256": f"sha256:{digest.hexdigest()}",
                    "size": actual_size,
                }
            )
            verified_paths.add(installed_path)
            continue
        if raw_path != record_relative:
            raise RuntimeError(f"unexpected unhashed duckdb RECORD path: {raw_path}")
        unhashed.append(raw_path)

    wheel_relative = next(
        (
            str(item)
            for item in distribution_files
            if str(item).endswith(".dist-info/WHEEL")
        ),
        "",
    )
    if not wheel_relative:
        raise RuntimeError("duckdb distribution has no WHEEL evidence")
    raw_wheel_path = Path(distribution.locate_file(wheel_relative))
    wheel_path = strict_path(
        raw_wheel_path,
        roots=site_roots,
        regular_file=True,
    )
    if wheel_path not in verified_paths:
        raise RuntimeError("DuckDB WHEEL is not RECORD-hash-bound")
    wheel_text = wheel_path.read_text(encoding="utf-8", errors="strict")
    wheel_tags = sorted(
        line.split(":", 1)[1].strip()
        for line in wheel_text.splitlines()
        if line.startswith("Tag:")
    )
    if not wheel_tags:
        raise RuntimeError("duckdb WHEEL declares no compatibility tags")

    base_python = _trusted_base_python_path()
    pyvenv_config = prefix / "pyvenv.cfg"
    pyvenv_text = (
        pyvenv_config.read_text(encoding="utf-8", errors="strict")
        if pyvenv_config.is_file() and not pyvenv_config.is_symlink()
        else ""
    )
    system_site_packages = any(
        line.partition("=")[2].strip().lower() == "true"
        for line in pyvenv_text.splitlines()
        if line.partition("=")[0].strip().lower() == "include-system-site-packages"
    )
    libc_name, libc_version = platform.libc_ver()
    installer_relative = next(
        (
            str(item)
            for item in distribution_files
            if str(item).endswith(".dist-info/INSTALLER")
        ),
        "",
    )
    installer = (
        Path(distribution.locate_file(installer_relative))
        .read_text(encoding="utf-8", errors="strict")
        .strip()
        if installer_relative
        else ""
    )

    artifact_root = prefix / "bootstrap-artifacts"
    wheel_archives = tuple(sorted(artifact_root.glob("*.whl")))
    if len(wheel_archives) != 1:
        raise RuntimeError("bootstrap evidence must retain exactly one DuckDB wheel")
    archive_path = strict_path(
        wheel_archives[0],
        roots=(artifact_root,),
        regular_file=True,
    )
    archive_sha256 = _sha256_file(archive_path)
    if archive_sha256 not in _bootstrap_allowed_wheel_hashes():
        raise RuntimeError("retained DuckDB wheel is not admitted by the bootstrap lock")
    report_path = strict_path(
        artifact_root / "pip-install-report.json",
        roots=(artifact_root,),
        regular_file=True,
    )
    report_bytes = report_path.read_bytes()
    if not report_bytes or len(report_bytes) > 2 * 1024 * 1024:
        raise RuntimeError("pip installation report has an invalid size")
    try:
        report = json.loads(report_bytes)
    except json.JSONDecodeError as exc:
        raise RuntimeError("pip installation report is not valid JSON") from exc
    installs = report.get("install") if isinstance(report, dict) else None
    if not isinstance(installs, list) or len(installs) != 1:
        raise RuntimeError("pip installation report must contain one distribution")
    installed = installs[0]
    metadata = installed.get("metadata") if isinstance(installed, dict) else None
    download_info = installed.get("download_info") if isinstance(installed, dict) else None
    archive_info = (
        download_info.get("archive_info") if isinstance(download_info, dict) else None
    )
    archive_hashes = (
        archive_info.get("hashes") if isinstance(archive_info, dict) else None
    )
    report_archive_sha256 = (
        f"sha256:{archive_hashes.get('sha256')}"
        if isinstance(archive_hashes, dict)
        else ""
    )
    report_archive_name = (
        Path(unquote(urlparse(str(download_info.get("url") or "")).path)).name
        if isinstance(download_info, dict)
        else ""
    )
    if (
        not isinstance(metadata, dict)
        or str(metadata.get("name") or "").lower() != "duckdb"
        or str(metadata.get("version") or "") != ".".join(map(str, REQUIRED_DUCKDB_VERSION))
        or report_archive_sha256 != archive_sha256
        or report_archive_name != archive_path.name
    ):
        raise RuntimeError("pip report does not bind the retained DuckDB wheel")

    # The retained, hash-admitted wheel is the content root of trust.  An
    # installed RECORD is useful evidence but is mutable alongside the files it
    # describes, so compare every wheel payload byte directly and reject every
    # site-packages file that is neither a wheel member nor one of pip's three
    # tightly modeled bookkeeping files.
    installed_site_root = distribution_root
    wheel_member_rows: list[dict[str, Any]] = []
    wheel_install_paths: set[str] = set()

    def installed_wheel_path(raw_name: str) -> str:
        if "\\" in raw_name:
            raise RuntimeError("DuckDB wheel contains a backslash path")
        source_path = PurePosixPath(raw_name)
        if source_path.is_absolute() or not source_path.parts or ".." in source_path.parts:
            raise RuntimeError(f"unsafe DuckDB wheel member path: {raw_name!r}")
        parts = source_path.parts
        if parts[0].endswith(".data"):
            if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
                raise RuntimeError(
                    f"DuckDB wheel contains an unsupported data-scheme member: {raw_name}"
                )
            parts = parts[2:]
        target = PurePosixPath(*parts)
        if target.is_absolute() or not target.parts or ".." in target.parts:
            raise RuntimeError(f"unsafe installed DuckDB wheel path: {raw_name!r}")
        return target.as_posix()

    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError("retained DuckDB wheel is not a valid zip archive") from exc
    with archive:
        seen_archive_names: set[str] = set()
        for info in archive.infolist():
            raw_name = str(info.filename)
            if raw_name in seen_archive_names:
                raise RuntimeError(f"DuckDB wheel contains a duplicate member: {raw_name}")
            seen_archive_names.add(raw_name)
            if info.flag_bits & 0x1:
                raise RuntimeError("encrypted DuckDB wheel members are not admitted")
            target_relative = installed_wheel_path(raw_name.rstrip("/"))
            if info.is_dir():
                continue
            file_type = (int(info.external_attr) >> 16) & 0o170000
            if file_type not in (0, stat.S_IFREG):
                raise RuntimeError(f"DuckDB wheel member is not a regular file: {raw_name}")
            if target_relative in wheel_install_paths:
                raise RuntimeError(
                    f"DuckDB wheel members collide after installation: {target_relative}"
                )
            wheel_install_paths.add(target_relative)
            archive_digest = hashlib.sha256()
            archive_size = 0
            try:
                member_handle = archive.open(info, "r")
            except (KeyError, RuntimeError, zipfile.BadZipFile) as exc:
                raise RuntimeError(f"DuckDB wheel member is unreadable: {raw_name}") from exc
            with member_handle:
                for chunk in iter(lambda: member_handle.read(1024 * 1024), b""):
                    archive_digest.update(chunk)
                    archive_size += len(chunk)
            if archive_size != int(info.file_size):
                raise RuntimeError(f"DuckDB wheel member size changed: {raw_name}")
            member_row = {
                "archive_path": raw_name,
                "installed_path": target_relative,
                "sha256": f"sha256:{archive_digest.hexdigest()}",
                "size": archive_size,
            }
            if target_relative != record_relative:
                installed_member = strict_path(
                    installed_site_root / target_relative,
                    roots=site_roots,
                    regular_file=True,
                )
                if (
                    installed_member.stat().st_size != archive_size
                    or _sha256_file(installed_member) != member_row["sha256"]
                ):
                    raise RuntimeError(
                        f"installed DuckDB file differs from admitted wheel: {target_relative}"
                    )
            else:
                member_row["installed_content"] = "pip-regenerated-record"
            wheel_member_rows.append(member_row)

    dist_info_root = PurePosixPath(record_relative).parent.as_posix()
    pip_generated_policy = {
        record_relative: None,
        f"{dist_info_root}/INSTALLER": b"pip\n",
        f"{dist_info_root}/REQUESTED": b"",
    }
    actual_site_files: set[str] = set()
    site_manifest_rows: list[dict[str, Any]] = []
    for candidate in sorted(
        installed_site_root.rglob("*"), key=lambda item: item.as_posix()
    ):
        relative = candidate.relative_to(installed_site_root).as_posix()
        try:
            candidate_metadata = candidate.lstat()
        except OSError as exc:
            raise RuntimeError(f"site-packages entry became unreadable: {relative}") from exc
        if stat.S_ISDIR(candidate_metadata.st_mode):
            continue
        if stat.S_ISLNK(candidate_metadata.st_mode) or not stat.S_ISREG(
            candidate_metadata.st_mode
        ):
            raise RuntimeError(f"site-packages contains an unsupported entry: {relative}")
        if relative.endswith((".pyc", ".pyo")):
            raise RuntimeError(f"site-packages contains executable bytecode: {relative}")
        actual_site_files.add(relative)
        site_manifest_rows.append(
            {
                "path": relative,
                "sha256": _sha256_file(candidate),
                "size": candidate_metadata.st_size,
            }
        )

    expected_site_files = set(wheel_install_paths)
    expected_site_files.discard(record_relative)
    for generated_path, exact_bytes in pip_generated_policy.items():
        generated = installed_site_root / generated_path
        if not generated.exists():
            if generated_path == record_relative:
                raise RuntimeError("installed DuckDB RECORD disappeared")
            continue
        generated = strict_path(generated, roots=site_roots, regular_file=True)
        if exact_bytes is not None and generated.read_bytes() != exact_bytes:
            raise RuntimeError(f"pip bookkeeping content mismatch: {generated_path}")
        expected_site_files.add(generated_path)
    unexpected_site_files = actual_site_files.difference(expected_site_files)
    missing_site_files = expected_site_files.difference(actual_site_files)
    if unexpected_site_files or missing_site_files:
        detail = {
            "unexpected": sorted(unexpected_site_files),
            "missing": sorted(missing_site_files),
        }
        raise RuntimeError(
            "site-packages does not exactly match the admitted DuckDB wheel: "
            + _canonical_json(detail)
        )

    # Import executable extension code only after the retained admitted wheel
    # and the entire site root have been verified byte-for-byte.  This prevents
    # a modified native module (or loose import hook) from executing before its
    # trust decision is complete.
    duckdb = importlib.import_module("duckdb")
    module_path = strict_path(
        Path(str(duckdb.__file__)),
        roots=site_roots,
        regular_file=True,
    )
    native_duckdb = importlib.import_module("_duckdb")
    native_module_path = strict_path(
        Path(str(native_duckdb.__file__)),
        roots=site_roots,
        regular_file=True,
    )
    if module_path not in verified_paths or native_module_path not in verified_paths:
        raise RuntimeError("imported DuckDB executable is not RECORD-hash-bound")

    launcher_path = strict_path(
        prefix / "bin/dqk-sealed-python",
        roots=(prefix,),
        regular_file=True,
    )
    launcher_metadata = launcher_path.stat()
    if (
        not launcher_metadata.st_mode & stat.S_IXUSR
        or launcher_metadata.st_mode & 0o077
    ):
        raise RuntimeError("sealed Python launcher permissions are not owner-execute-only")
    expected_launcher = _sealed_python_launcher_content(
        _sealed_python_paths()
    ).encode("utf-8")
    if launcher_path.read_bytes() != expected_launcher:
        raise RuntimeError("sealed Python launcher content does not match policy")

    distributions = []
    for installed_distribution in importlib.metadata.distributions():
        raw_root = Path(installed_distribution.locate_file(""))
        installed_root = strict_path(
            raw_root,
            roots=site_roots,
            regular_file=False,
        )
        distributions.append(
            {
                "name": str(installed_distribution.metadata.get("Name") or "").lower(),
                "version": str(installed_distribution.version),
                "root": str(installed_root),
            }
        )
    distributions.sort(key=lambda item: (item["name"], item["version"], item["root"]))
    stdlib_manifest_sha256, stdlib_manifest_file_count = base_runtime_manifest()
    stdlib_zip_present, stdlib_zip_sha256 = stdlib_zip_evidence()
    verified.sort(key=lambda item: str(item["path"]))
    wheel_member_rows.sort(key=lambda item: str(item["installed_path"]))
    site_manifest_rows.sort(key=lambda item: str(item["path"]))
    return {
        "environment_root": str(prefix),
        "python_executable": os.environ.get(
            "IPFS_DATASETS_DQK_PYTHON_EXECUTABLE",
            str(Path(sys.executable).absolute()),
        ),
        "sealed_python_launcher_path": str(launcher_path),
        "sealed_python_launcher_sha256": _sha256_file(launcher_path),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_cache_tag": str(sys.implementation.cache_tag),
        "base_prefix": str(base_prefix),
        "base_python_executable": str(base_python),
        "base_python_sha256": _sha256_file(base_python),
        "isolated_environment": prefix != base_prefix,
        "system_site_packages": system_site_packages,
        "pyvenv_config_sha256": _sha256_file(pyvenv_config) if pyvenv_text else "",
        "python_sys_path": list(sys.path),
        "python_flags": {
            "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
            "isolated": bool(sys.flags.isolated),
            "no_site": bool(sys.flags.no_site),
            "no_user_site": bool(sys.flags.no_user_site),
            "safe_path": bool(sys.flags.safe_path),
        },
        "stdlib_root": str(stdlib_root),
        "stdlib_zip_path": str(stdlib_zip),
        "stdlib_zip_present": stdlib_zip_present,
        "stdlib_zip_sha256": stdlib_zip_sha256,
        "dynload_root": str(dynload_root),
        "stdlib_manifest_sha256": stdlib_manifest_sha256,
        "stdlib_manifest_file_count": stdlib_manifest_file_count,
        "site_package_roots": [str(root.resolve()) for root in site_roots],
        "site_packages_manifest_sha256": (
            f"sha256:{_sha256_text(_canonical_json(site_manifest_rows))}"
        ),
        "site_packages_manifest_file_count": len(site_manifest_rows),
        "installed_distributions": distributions,
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "sysconfig_platform": sysconfig.get_platform(),
            "libc": [libc_name, libc_version],
        },
        "duckdb_distribution_name": str(distribution.metadata.get("Name") or ""),
        "duckdb_distribution_version": str(distribution.version),
        "duckdb_version": str(duckdb.__version__),
        "duckdb_module_path": str(module_path),
        "duckdb_module_sha256": _sha256_file(module_path),
        "duckdb_native_module_path": str(native_module_path),
        "duckdb_native_module_sha256": _sha256_file(native_module_path),
        "duckdb_distribution_root": str(distribution_root),
        "duckdb_record_path": str(record_path),
        "duckdb_record_sha256": f"sha256:{hashlib.sha256(record_bytes).hexdigest()}",
        "duckdb_record_evidence_sha256": (
            f"sha256:{_sha256_text(_canonical_json(verified))}"
        ),
        "duckdb_record_verified_file_count": len(verified),
        "duckdb_record_unhashed_paths": sorted(unhashed),
        "duckdb_wheel_path": str(wheel_path),
        "duckdb_wheel_sha256": _sha256_file(wheel_path),
        "duckdb_wheel_tags": wheel_tags,
        "duckdb_installer": installer,
        "duckdb_install_archive_path": str(archive_path),
        "duckdb_install_archive_sha256": archive_sha256,
        "duckdb_wheel_member_evidence_sha256": (
            f"sha256:{_sha256_text(_canonical_json(wheel_member_rows))}"
        ),
        "duckdb_wheel_member_count": len(wheel_member_rows),
        "pip_install_report_path": str(report_path),
        "pip_install_report_sha256": (
            f"sha256:{hashlib.sha256(report_bytes).hexdigest()}"
        ),
        "pip_install_report_version": str(report.get("version") or ""),
    }


def _environment_python() -> Path:
    return EXPECTED_ENV_ROOT / "bin/python"


def _sealed_python_paths() -> list[str]:
    """Return the only import roots admitted by the no-site launcher."""

    import sysconfig

    stdlib_root = Path(sysconfig.get_path("stdlib")).resolve()
    return [
        str(
            stdlib_root.parent
            / f"python{BOOTSTRAP_SUPPORTED_PYTHON[0]}{BOOTSTRAP_SUPPORTED_PYTHON[1]}.zip"
        ),
        str(stdlib_root),
        str(stdlib_root / "lib-dynload"),
        str(
            EXPECTED_ENV_ROOT
            / "lib"
            / f"python{BOOTSTRAP_SUPPORTED_PYTHON[0]}.{BOOTSTRAP_SUPPORTED_PYTHON[1]}"
            / "site-packages"
        ),
    ]


def _sealed_python_dispatch_source(python_paths: Sequence[str]) -> str:
    """Return the exact ``python -c`` policy embedded in the sealed wrapper."""

    import_paths = [str(ACCELERATE_ROOT.resolve()), *[str(item) for item in python_paths]]
    base_python = str(_trusted_base_python_path())
    environment_python = _environment_python().absolute()
    site_root = str(python_paths[-1])
    program_path = str(Path(__file__).resolve())
    sealed_environment = _sealed_python_environment()
    manual_modules = (
        "ipfs_datasets_py.duckdb_control.inventory_refinement",
        "ipfs_datasets_py.ducklake.cutover",
    )
    manual_scripts = (
        str(
            REPO_ROOT
            / "scripts/validation/validate_accelerate_duckdb_quack_release.py"
        ),
        str(REPO_ROOT / "scripts/ops/ipfs_datasets_duckdb_quack_lifecycle.py"),
    )
    return "\n".join(
        (
            "import os, runpy, sys",
            f"sys.path[:] = {import_paths!r}",
            f"sys.prefix = sys.exec_prefix = {str(EXPECTED_ENV_ROOT)!r}",
            f"sealed_environment = {sealed_environment!r}",
            "for _dqk_name in tuple(os.environ):",
            "    if (_dqk_name.startswith('PYTHON') or "
            "_dqk_name.startswith('LD_') or "
            "_dqk_name.startswith('IPFS_ACCELERATE_AGENT_VALIDATION_') or "
            "_dqk_name.startswith('IPFS_DATASETS_DQK_VALIDATION_') or "
            f"_dqk_name in {tuple(_ACCELERATE_IMPORT_ENVIRONMENT)!r}):",
            "        os.environ.pop(_dqk_name, None)",
            "os.environ.update(sealed_environment)",
            f"os.environ['IPFS_DATASETS_DQK_ENV_ROOT'] = {str(EXPECTED_ENV_ROOT)!r}",
            f"os.environ['IPFS_DATASETS_DQK_BASE_PYTHON'] = {base_python!r}",
            f"os.environ['IPFS_DATASETS_DQK_PYTHON_EXECUTABLE'] = {str(environment_python)!r}",
            "args = sys.argv[1:]",
            "if ((len(args) >= 2 and not args[0].startswith('-') and "
            f"os.path.realpath(args[0]) == {program_path!r} and "
            "args[1] == 'bootstrap-environment') "
            "or (len(args) >= 3 and args[0] == '-m' and "
            "args[1] == 'scripts.ops.ipfs_datasets_duckdb_quack_program' and "
            "args[2] == 'bootstrap-environment')):",
            "    raise SystemExit('sealed Python cannot dispatch bootstrap-environment; "
            "invoke the program with the trusted base interpreter')",
            f"policy = runpy.run_path({program_path!r})",
            "_dqk_environment_lock = policy['_acquire_environment_lifecycle_lock'](exclusive=False)",
            "policy['_local_environment_probe']("
            f"environment_root={str(EXPECTED_ENV_ROOT)!r}, sealed_site_roots=[{site_root!r}])",
            "policy['_install_task_validation_runtime_adapter']()",
            "if len(args) >= 2 and args[0] == '--dqk-manual-module':",
            "    module = args[1]",
            f"    assert module in {manual_modules!r}, 'manual verifier module is not allowlisted'",
            f"    sys.path.insert(0, {str(REPO_ROOT.resolve())!r})",
            "    sys.argv = [module, *args[2:]]",
            "    runpy.run_module(module, run_name='__main__', alter_sys=True)",
            "elif len(args) >= 2 and args[0] == '--dqk-manual-script':",
            "    script = args[1]",
            f"    assert script in {manual_scripts!r}, 'manual verifier script is not allowlisted'",
            f"    sys.path.insert(0, {str(REPO_ROOT.resolve())!r})",
            "    sys.argv = [script, *args[2:]]",
            "    runpy.run_path(script, run_name='__main__')",
            "elif len(args) >= 2 and args[0] == '-m':",
            "    module = args[1]",
            "    sys.argv = [module, *args[2:]]",
            "    runpy.run_module(module, run_name='__main__', alter_sys=True)",
            "elif args and not args[0].startswith('-'):",
            "    script = args[0]",
            "    sys.argv = args",
            "    runpy.run_path(script, run_name='__main__')",
            "else:",
            "    raise SystemExit('sealed Python requires an allowlisted dispatch mode')",
        )
    )


def _sealed_python_launcher_content(python_paths: Sequence[str]) -> str:
    """Build the immutable wrapper that dispatches modules/scripts without site.py."""

    base_python = _trusted_base_python_path()
    source = _sealed_python_dispatch_source(python_paths)
    environment_exports = "".join(
        f"export {key}={shlex.quote(value)}\n"
        for key, value in sorted(_sealed_python_environment().items())
    )
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        "unset LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT LD_DEBUG LD_PROFILE "
        "LD_BIND_NOW LD_ORIGIN_PATH LD_DYNAMIC_WEAK LD_HWCAP_MASK || true\n"
        f"{environment_exports}"
        f"exec {shlex.quote(str(base_python))} -I -B -S -c "
        f"{shlex.quote(source)} \"$@\"\n"
    )


def _write_sealed_python_launcher() -> None:
    content = _sealed_python_launcher_content(_sealed_python_paths())
    _atomic_write_text(SEALED_PYTHON_LAUNCHER, content)
    os.chmod(SEALED_PYTHON_LAUNCHER, 0o500)
    with SEALED_PYTHON_LAUNCHER.open("rb") as handle:
        os.fsync(handle.fileno())
    directory_fd = os.open(SEALED_PYTHON_LAUNCHER.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _run_environment_probe(
    python_executable: Path,
    *,
    _lifecycle_lock_held: bool = False,
) -> dict[str, Any]:
    if not _lifecycle_lock_held:
        with _environment_lifecycle_lock(exclusive=False):
            return _run_environment_probe(
                python_executable,
                _lifecycle_lock_held=True,
            )

    import stat

    environment_root = python_executable.absolute().parent.parent
    base_python = _trusted_base_python_path()
    try:
        resolved_environment_python = python_executable.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("environment Python launcher is unavailable") from exc
    if resolved_environment_python != base_python:
        raise RuntimeError("environment Python does not resolve to the admitted base interpreter")
    descriptor = os.open(
        base_python,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    base_metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(base_metadata.st_mode)
        or base_metadata.st_uid != 0
        or base_metadata.st_mode & 0o022
    ):
        os.close(descriptor)
        raise RuntimeError("base Python interpreter is not root-owned and immutable")
    site_root = (
        environment_root
        / "lib"
        / f"python{BOOTSTRAP_SUPPORTED_PYTHON[0]}.{BOOTSTRAP_SUPPORTED_PYTHON[1]}"
        / "site-packages"
    )
    probe_script = (
        "import json,runpy,sys; "
        f"sys.path.append({str(site_root)!r}); "
        f"m=runpy.run_path({str(Path(__file__).resolve())!r}); "
        "print(json.dumps(m['_local_environment_probe']("
        f"environment_root={str(environment_root)!r},"
        f"sealed_site_roots=[{str(site_root)!r}]),sort_keys=True))"
    )
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("PYTHON") or key.startswith("LD_"):
            environment.pop(key)
    environment["IPFS_DATASETS_DQK_ENV_ROOT"] = str(environment_root)
    environment["IPFS_DATASETS_DQK_BASE_PYTHON"] = str(base_python)
    environment["IPFS_DATASETS_DQK_PYTHON_EXECUTABLE"] = str(
        python_executable.absolute()
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    try:
        result = subprocess.run(
            [f"/proc/self/fd/{descriptor}", "-I", "-B", "-S", "-c", probe_script],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            pass_fds=(descriptor,),
        )
    finally:
        os.close(descriptor)
    if result.returncode:
        raise RuntimeError(
            "environment probe failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("environment probe did not return one JSON object") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("environment probe returned a non-object")
    return payload


def _bootstrap_artifact_evidence() -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in (
        Path(__file__).resolve(),
        MANUAL_GATE_AUTHORITY_MODULE,
        BOOTSTRAP_REQUIREMENTS,
        BOOTSTRAP_VALIDATOR,
        BOOTSTRAP_VALIDATOR_REQUIREMENTS,
    ):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(REPO_ROOT.resolve())
        except ValueError as exc:
            raise RuntimeError(f"bootstrap artifact escapes repository: {path}") from exc
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"bootstrap artifact must be a regular file: {path}")
        artifacts[relative.as_posix()] = _sha256_file(path)
    if artifacts.get(BOOTSTRAP_REQUIREMENTS.relative_to(REPO_ROOT).as_posix()) != (
        BOOTSTRAP_REQUIREMENTS_SHA256
    ):
        raise RuntimeError("checked-in bootstrap requirements policy digest mismatch")
    if artifacts.get(
        BOOTSTRAP_VALIDATOR_REQUIREMENTS.relative_to(REPO_ROOT).as_posix()
    ) != BOOTSTRAP_VALIDATOR_REQUIREMENTS_SHA256:
        raise RuntimeError("checked-in validator requirements policy digest mismatch")
    if artifacts.get(BOOTSTRAP_VALIDATOR.relative_to(REPO_ROOT).as_posix()) != (
        BOOTSTRAP_VALIDATOR_SHA256
    ):
        raise RuntimeError("checked-in validator module digest mismatch")
    return dict(sorted(artifacts.items()))


def _bootstrap_allowed_wheel_hashes() -> frozenset[str]:
    try:
        text = BOOTSTRAP_REQUIREMENTS.read_text(encoding="utf-8", errors="strict")
    except OSError as exc:
        raise RuntimeError("bootstrap requirements policy is unreadable") from exc
    hashes = frozenset(
        f"sha256:{value}"
        for value in re.findall(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)", text)
    )
    if len(hashes) != len(BOOTSTRAP_SUPPORTED_MACHINES):
        raise RuntimeError("bootstrap requirements must admit one wheel per platform")
    return hashes


def _bootstrap_repository_evidence() -> dict[str, Any]:
    artifacts = _bootstrap_artifact_evidence()
    paths = tuple(artifacts)
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", *paths],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if tracked.returncode:
        raise RuntimeError("bootstrap artifacts must be checked in before environment creation")
    changed = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *paths],
        cwd=REPO_ROOT,
        check=False,
    )
    if changed.returncode != 0:
        raise RuntimeError("bootstrap artifacts must match HEAD before environment creation")
    return {
        "repository_root": str(REPO_ROOT.resolve()),
        "commit": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "artifacts": artifacts,
    }


def _git_blob_sha256(commit: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return ""
    return f"sha256:{hashlib.sha256(result.stdout).hexdigest()}"


def _bootstrap_repository_evidence_valid(evidence: Any) -> tuple[bool, str]:
    if not isinstance(evidence, dict) or set(evidence) != {
        "repository_root",
        "commit",
        "tree",
        "artifacts",
    }:
        return False, "repository evidence shape mismatch"
    commit = str(evidence.get("commit") or "")
    tree = str(evidence.get("tree") or "")
    artifacts = evidence.get("artifacts")
    if (
        evidence.get("repository_root") != str(REPO_ROOT.resolve())
        or re.fullmatch(r"[0-9a-f]{40}", commit) is None
        or re.fullmatch(r"[0-9a-f]{40}", tree) is None
        or not isinstance(artifacts, dict)
    ):
        return False, "repository evidence values are invalid"
    try:
        current_artifacts = _bootstrap_artifact_evidence()
        recorded_tree = _git("rev-parse", f"{commit}^{{tree}}")
    except RuntimeError as exc:
        return False, str(exc)
    if artifacts != current_artifacts or tree != recorded_tree:
        return False, "bootstrap artifact or repository tree evidence changed"
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if ancestry.returncode:
        return False, "environment receipt commit is not an ancestor of HEAD"
    for relative_path, digest in artifacts.items():
        if _git_blob_sha256(commit, str(relative_path)) != digest:
            return False, f"bootstrap artifact is not bound at receipt commit: {relative_path}"
    return True, f"commit={commit}; tree={tree}"


def _bootstrap_probe_compatible(probe: Any) -> tuple[bool, str]:
    if not isinstance(probe, dict):
        return False, "environment probe is not an object"
    expected_keys = {
        "environment_root",
        "python_executable",
        "sealed_python_launcher_path",
        "sealed_python_launcher_sha256",
        "python_version",
        "python_implementation",
        "python_cache_tag",
        "base_prefix",
        "base_python_executable",
        "base_python_sha256",
        "isolated_environment",
        "system_site_packages",
        "pyvenv_config_sha256",
        "python_sys_path",
        "python_flags",
        "stdlib_root",
        "stdlib_zip_path",
        "stdlib_zip_present",
        "stdlib_zip_sha256",
        "dynload_root",
        "stdlib_manifest_sha256",
        "stdlib_manifest_file_count",
        "site_package_roots",
        "site_packages_manifest_sha256",
        "site_packages_manifest_file_count",
        "installed_distributions",
        "platform",
        "duckdb_distribution_name",
        "duckdb_distribution_version",
        "duckdb_version",
        "duckdb_module_path",
        "duckdb_module_sha256",
        "duckdb_native_module_path",
        "duckdb_native_module_sha256",
        "duckdb_distribution_root",
        "duckdb_record_path",
        "duckdb_record_sha256",
        "duckdb_record_evidence_sha256",
        "duckdb_record_verified_file_count",
        "duckdb_record_unhashed_paths",
        "duckdb_wheel_path",
        "duckdb_wheel_sha256",
        "duckdb_wheel_tags",
        "duckdb_installer",
        "duckdb_install_archive_path",
        "duckdb_install_archive_sha256",
        "duckdb_wheel_member_evidence_sha256",
        "duckdb_wheel_member_count",
        "pip_install_report_path",
        "pip_install_report_sha256",
        "pip_install_report_version",
    }
    if set(probe) != expected_keys:
        return False, "environment probe shape mismatch"
    platform_evidence = probe.get("platform")
    if not isinstance(platform_evidence, dict) or set(platform_evidence) != {
        "system",
        "machine",
        "sysconfig_platform",
        "libc",
    }:
        return False, "platform evidence shape mismatch"
    python_version = _version_tuple(str(probe.get("python_version") or ""))
    required_version = ".".join(map(str, REQUIRED_DUCKDB_VERSION))
    if probe.get("environment_root") != str(EXPECTED_ENV_ROOT):
        return False, "environment prefix mismatch"
    if probe.get("python_executable") != str(_environment_python().absolute()):
        return False, "environment Python executable mismatch"
    if probe.get("sealed_python_launcher_path") != str(SEALED_PYTHON_LAUNCHER):
        return False, "sealed Python launcher path mismatch"
    if (
        python_version[:2] != BOOTSTRAP_SUPPORTED_PYTHON
        or probe.get("python_implementation") != "CPython"
        or platform_evidence.get("system") != BOOTSTRAP_SUPPORTED_SYSTEM
        or platform_evidence.get("machine") not in BOOTSTRAP_SUPPORTED_MACHINES
    ):
        return False, "unsupported bootstrap Python or platform"
    if not probe.get("isolated_environment") or probe.get("system_site_packages"):
        return False, "target is not the dedicated isolated virtual environment"
    python_flags = probe.get("python_flags")
    if python_flags != {
        "dont_write_bytecode": True,
        "isolated": True,
        "no_site": True,
        "no_user_site": True,
        "safe_path": True,
    }:
        return False, "bootstrap probe did not use the sealed interpreter flags"
    site_roots = [str(item) for item in (probe.get("site_package_roots") or ())]
    expected_sys_path = [
        str(probe.get("stdlib_zip_path") or ""),
        str(probe.get("stdlib_root") or ""),
        str(probe.get("dynload_root") or ""),
        *site_roots,
    ]
    if probe.get("python_sys_path") != expected_sys_path:
        return False, "bootstrap interpreter sys.path contains foreign roots"
    if probe.get("installed_distributions") != [
        {
            "name": "duckdb",
            "version": required_version,
            "root": site_roots[0] if len(site_roots) == 1 else "",
        }
    ]:
        return False, "bootstrap environment contains foreign distributions"
    for key in (
        "duckdb_distribution_root",
        "duckdb_module_path",
        "duckdb_native_module_path",
        "duckdb_record_path",
        "duckdb_wheel_path",
        "duckdb_install_archive_path",
        "pip_install_report_path",
        "sealed_python_launcher_path",
    ):
        try:
            Path(str(probe.get(key) or "")).absolute().relative_to(EXPECTED_ENV_ROOT)
        except ValueError:
            return False, f"environment evidence path escapes target: {key}"
    if (
        str(probe.get("duckdb_distribution_name") or "").lower() != "duckdb"
        or probe.get("duckdb_distribution_version") != required_version
        or probe.get("duckdb_version") != required_version
        or probe.get("duckdb_installer") != "pip"
        or _safe_int(probe.get("duckdb_record_verified_file_count")) < 1
        or _safe_int(probe.get("duckdb_wheel_member_count")) < 1
        or _safe_int(probe.get("site_packages_manifest_file_count")) < 1
        or not probe.get("duckdb_wheel_tags")
        or probe.get("duckdb_record_unhashed_paths")
        != [f"duckdb-{required_version}.dist-info/RECORD"]
        or probe.get("duckdb_install_archive_sha256")
        not in _bootstrap_allowed_wheel_hashes()
        or not probe.get("pip_install_report_version")
    ):
        return False, "DuckDB distribution or wheel evidence mismatch"
    expected_tag_fragment = f"cp312-cp312-{platform_evidence['machine']}"
    if not any(
        expected_tag_fragment in str(tag).replace("manylinux_2_26_", "").replace(
            "manylinux_2_28_", ""
        )
        for tag in probe["duckdb_wheel_tags"]
    ):
        return False, "DuckDB WHEEL tags do not bind the bootstrap platform"
    for key in (
        "base_python_sha256",
        "sealed_python_launcher_sha256",
        "pyvenv_config_sha256",
        "duckdb_module_sha256",
        "duckdb_native_module_sha256",
        "duckdb_record_sha256",
        "duckdb_record_evidence_sha256",
        "duckdb_wheel_sha256",
        "duckdb_install_archive_sha256",
        "pip_install_report_sha256",
        "stdlib_manifest_sha256",
        "site_packages_manifest_sha256",
        "duckdb_wheel_member_evidence_sha256",
    ):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", str(probe.get(key) or "")) is None:
            return False, f"invalid environment evidence digest: {key}"
    stdlib_zip_present = probe.get("stdlib_zip_present")
    stdlib_zip_sha256 = str(probe.get("stdlib_zip_sha256") or "")
    if not isinstance(stdlib_zip_present, bool):
        return False, "stdlib zip presence evidence is invalid"
    if stdlib_zip_present:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", stdlib_zip_sha256) is None:
            return False, "present stdlib zip is not digest-bound"
    elif stdlib_zip_sha256:
        return False, "absent stdlib zip unexpectedly has a digest"
    return True, f"duckdb={required_version}; record={probe['duckdb_record_evidence_sha256']}"


def _live_runtime_import_contract(
    bootstrap_probe: Mapping[str, Any],
) -> tuple[bool, str]:
    """Prove the live CLI/master interpreter cannot see foreign Python code."""

    expected_path = [
        str(ACCELERATE_ROOT.resolve()),
        *[str(item) for item in bootstrap_probe.get("python_sys_path") or ()],
    ]
    actual_path = [str(item) for item in sys.path]
    if actual_path != expected_path:
        return False, (
            "live sys.path is not sealed; expected="
            + _canonical_json(expected_path)
            + "; actual="
            + _canonical_json(actual_path)
        )
    expected_flags = {
        "dont_write_bytecode": True,
        "isolated": True,
        "no_site": True,
        "no_user_site": True,
        "safe_path": True,
    }
    actual_flags = {
        "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
        "isolated": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "no_user_site": bool(sys.flags.no_user_site),
        "safe_path": bool(sys.flags.safe_path),
    }
    if actual_flags != expected_flags:
        return False, f"live Python flags are not sealed: {_canonical_json(actual_flags)}"
    try:
        live_executable = Path(sys.executable).resolve(strict=True)
        probe_base_executable = Path(
            str(bootstrap_probe.get("base_python_executable") or "")
        ).resolve(strict=True)
        admitted_base_executable = _trusted_base_python_path()
    except OSError:
        return False, "live base interpreter evidence is unavailable"
    if Path(sys.prefix).resolve() != EXPECTED_ENV_ROOT:
        return False, "live interpreter prefix is not the admitted environment root"
    if (
        live_executable != admitted_base_executable
        or live_executable != probe_base_executable
        or _sha256_file(live_executable)
        != str(bootstrap_probe.get("base_python_sha256") or "")
    ):
        return False, "live interpreter is not the receipt-bound base Python"
    if (
        Path(str(bootstrap_probe.get("python_executable") or "")).absolute()
        != _environment_python().absolute()
        or os.environ.get("IPFS_DATASETS_DQK_ENV_ROOT") != str(EXPECTED_ENV_ROOT)
        or os.environ.get("IPFS_DATASETS_DQK_BASE_PYTHON")
        != str(admitted_base_executable)
        or os.environ.get("IPFS_DATASETS_DQK_PYTHON_EXECUTABLE")
        != str(_environment_python().absolute())
    ):
        return False, "live interpreter lost the admitted environment evidence"
    python_environment = _runtime_python_environment(os.environ)
    expected_environment = _sealed_python_environment()
    if python_environment != expected_environment:
        return False, "live interpreter has foreign Python/import environment variables"
    return True, f"sys.path={_canonical_json(actual_path)}"


def _bootstrap_install_argv() -> list[str]:
    return [
        str(_environment_python()),
        "-m",
        "pip",
        "--isolated",
        "install",
        "--disable-pip-version-check",
        "--no-deps",
        "--no-index",
        "--require-hashes",
        "--only-binary=:all:",
        "--ignore-installed",
        "--no-compile",
        "--find-links",
        str(EXPECTED_ENV_ROOT / "bootstrap-artifacts"),
        "--report",
        str(EXPECTED_ENV_ROOT / "bootstrap-artifacts/pip-install-report.json"),
        "--requirement",
        str(BOOTSTRAP_REQUIREMENTS),
    ]


def _bootstrap_download_argv() -> list[str]:
    return [
        str(_environment_python()),
        "-m",
        "pip",
        "--isolated",
        "download",
        "--disable-pip-version-check",
        "--no-deps",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-cache-dir",
        "--dest",
        str(EXPECTED_ENV_ROOT / "bootstrap-artifacts"),
        "--requirement",
        str(BOOTSTRAP_REQUIREMENTS),
    ]


def _bootstrap_remove_installer_argv() -> list[str]:
    return [
        str(_environment_python()),
        "-m",
        "pip",
        "--isolated",
        "uninstall",
        "--yes",
        "pip",
    ]


def _environment_receipt_payload(
    probe: Mapping[str, Any],
    repository: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": BOOTSTRAP_ENVIRONMENT_RECEIPT_SCHEMA,
        "program_id": PROGRAM_ID,
        "attestation_scope": "bootstrap-only-duckdb-runtime",
        "quack_extension_attested": False,
        "environment_root": str(EXPECTED_ENV_ROOT),
        "requirements": {
            "path": BOOTSTRAP_REQUIREMENTS.relative_to(REPO_ROOT).as_posix(),
            "sha256": BOOTSTRAP_REQUIREMENTS_SHA256,
            "requires_hashes": True,
            "binary_only": True,
            "dependencies_disabled": True,
        },
        "repository": dict(repository),
        "creation_policy": {
            "system_site_packages": False,
            "clear_existing": False,
            "upgrade_existing": False,
            "sealed_launcher": str(SEALED_PYTHON_LAUNCHER),
            "sealed_launcher_flags": ["-I", "-B", "-S"],
            "pip_download_argv": _bootstrap_download_argv(),
            "pip_install_argv": _bootstrap_install_argv(),
            "pip_remove_installer_argv": _bootstrap_remove_installer_argv(),
        },
        "probe": dict(probe),
    }
    payload["receipt_id"] = (
        f"receipt:sha256:{_sha256_text(_canonical_json(payload))}"
    )
    return payload


def _validate_environment_receipt(
    receipt: Any,
    probe: Mapping[str, Any],
) -> tuple[bool, str]:
    if not isinstance(receipt, dict) or set(receipt) != {
        "schema",
        "receipt_id",
        "program_id",
        "attestation_scope",
        "quack_extension_attested",
        "environment_root",
        "requirements",
        "repository",
        "creation_policy",
        "probe",
    }:
        return False, "environment receipt shape mismatch"
    compatible, detail = _bootstrap_probe_compatible(probe)
    if not compatible:
        return False, detail
    repository_valid, repository_detail = _bootstrap_repository_evidence_valid(
        receipt.get("repository")
    )
    if not repository_valid:
        return False, repository_detail
    expected = _environment_receipt_payload(probe, receipt["repository"])
    if receipt != expected:
        return False, "environment receipt is not the exact live evidence projection"
    return True, f"{receipt['receipt_id']}; {repository_detail}"


def _assert_safe_bootstrap_target() -> None:
    root = EXPECTED_ENV_ROOT
    if not root.is_absolute() or len(root.parts) < 4:
        raise RuntimeError(f"unsafe environment root: {root}")
    forbidden = {
        Path("/").resolve(),
        Path.home().resolve(),
        REPO_ROOT.resolve(),
        Path(sys.base_prefix).resolve(),
    }
    if root.resolve() in forbidden or REPO_ROOT.resolve() in root.resolve().parents:
        raise RuntimeError(f"environment root overlaps a protected location: {root}")
    if ENVIRONMENT_RECEIPT != root / "environment-receipt.json":
        raise RuntimeError("environment receipt path is not bound to EXPECTED_ENV_ROOT")
    if root.is_symlink():
        raise RuntimeError("environment root must not be a symlink")


def _timestamp_age_seconds(value: Any, *, now: float) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return round(max(0.0, now - parsed.timestamp()), 1)
    except ValueError:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _lane_is_expectedly_idle(lane: Mapping[str, Any]) -> bool:
    """Return whether a bound lane is explicitly idle because it owns no work."""

    return bool(
        not str(lane.get("active_task_id") or "")
        and str(lane.get("selection_idle_reason") or "")
        in EXPECTED_IDLE_SELECTION_REASONS
    )


def _lane_task_heartbeat_is_stale(
    lane: Mapping[str, Any],
    *,
    stale_seconds: float,
) -> bool:
    """Distinguish an event-idle shard from a dead or wedged task daemon."""

    worker_active = bool(
        lane.get("active_task_id")
        and _safe_int(lane.get("active_worker_count")) > 0
        and not lane.get("stalled_without_active_worker")
    )
    heartbeat_age = lane.get("heartbeat_age_seconds")
    heartbeat_stale = bool(
        not isinstance(heartbeat_age, (int, float))
        or float(heartbeat_age) > stale_seconds
    )
    return bool(
        heartbeat_stale
        and not worker_active
        and not _lane_is_expectedly_idle(lane)
    )


def _attempt_limit_projection(
    state_payload: Mapping[str, Any],
    *,
    task_alias_by_cid: Mapping[str, str],
    eligible_task_aliases: Iterable[str],
    max_attempts: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Project both legacy display-ID and canonical-CID attempt ledgers."""

    display_value = state_payload.get("implementation_attempts")
    cid_value = state_payload.get("implementation_attempts_by_cid")
    display_attempts = {
        str(task_id): _safe_int(attempt)
        for task_id, attempt in (
            display_value.items() if isinstance(display_value, Mapping) else ()
        )
    }
    cid_attempts = {
        str(task_cid): _safe_int(attempt)
        for task_cid, attempt in (
            cid_value.items() if isinstance(cid_value, Mapping) else ()
        )
    }
    eligible = {str(alias) for alias in eligible_task_aliases}
    aliases = set(display_attempts).intersection(eligible)
    aliases.update(
        mapped_alias
        for task_cid, mapped_alias in task_alias_by_cid.items()
        if task_cid in cid_attempts and mapped_alias in eligible
    )
    limited: set[str] = set()
    divergences: list[dict[str, Any]] = []
    for alias in sorted(aliases):
        matching_cids = tuple(
            task_cid
            for task_cid, mapped_alias in task_alias_by_cid.items()
            if mapped_alias == alias
        )
        display_count = display_attempts.get(alias, 0)
        canonical_count = max(
            (cid_attempts.get(task_cid, 0) for task_cid in matching_cids),
            default=0,
        )
        if max_attempts > 0 and max(display_count, canonical_count) >= max_attempts:
            limited.add(alias)
        if matching_cids and display_count != canonical_count:
            divergences.append(
                {
                    "task_id": alias,
                    "task_cids": list(matching_cids),
                    "display_attempts": display_count,
                    "canonical_attempts": canonical_count,
                }
            )
    return sorted(limited), divergences


def task_status(source: Any) -> dict[str, Any]:
    snapshot, tables, _row_counts = _consistent_rows(
        source,
        ("tasks", "task_dependencies", "task_events", "materialization_receipts"),
    )
    tasks = tables["tasks"]
    dependencies = tables["task_dependencies"]
    bootstrap_row = next(
        (
            row
            for row in tasks
            if str(row.get("task_alias") or "") == BOOTSTRAP_TASK_ID
        ),
        None,
    )
    bootstrap_completion_evidence_id = ""
    if bootstrap_row is not None and str(bootstrap_row.get("status") or "") == "completed":
        bootstrap_evidence, _bootstrap_receipt = (
            _bootstrap_completion_evidence_from_tables(
                source,
                snapshot,
                tasks,
                tables["task_events"],
            )
        )
        bootstrap_completion_evidence_id = str(
            bootstrap_evidence["evidence_id"]
        )
    hold_projection = _manual_gate_hold_projection_from_tables(
        snapshot,
        tasks,
        dependencies,
        tables["task_events"],
        tables["materialization_receipts"],
        _repository_task_source_writer(source),
    )
    held_task_ids = set(hold_projection["held_task_aliases"])
    counts = Counter(str(row["status"]) for row in tasks)
    terminal_statuses = {"completed", "cancelled", "skipped", "failed", "quarantined"}
    terminal = sum(value for key, value in counts.items() if key in terminal_statuses)
    succeeded = int(counts.get("completed", 0))
    terminal_failures = {
        key: int(counts.get(key, 0))
        for key in ("failed", "quarantined", "cancelled", "skipped")
        if int(counts.get(key, 0))
    }
    rows_by_cid = {str(row["task_cid"]): row for row in tasks}
    completed_cids = {
        task_cid
        for task_cid, row in rows_by_cid.items()
        if str(row["status"]) in {"completed", "skipped"}
    }
    blocked_cids = {
        task_cid
        for task_cid, row in rows_by_cid.items()
        if str(row["status"]) == "blocked"
    }
    dependencies_by_task: dict[str, set[str]] = {
        task_cid: set() for task_cid in rows_by_cid
    }
    for row in dependencies:
        dependencies_by_task[str(row["task_cid"])].add(
            str(row["dependency_task_cid"])
        )
    ready_statuses = {"proposed", "admitted", "pending", "ready", "retrying"}
    ready_task_ids = sorted(
        str(row["task_alias"])
        for task_cid, row in rows_by_cid.items()
        if str(row["status"]) in ready_statuses
        and dependencies_by_task[task_cid].issubset(completed_cids)
        and not dependencies_by_task[task_cid].intersection(blocked_cids)
        and str(row["task_alias"]) not in held_task_ids
    )
    blocked_gates: list[dict[str, Any]] = []
    gate_authorization = {
        str(item["task_id"]): item for item in hold_projection["gates"]
    }
    for row in tasks:
        alias = str(row["task_alias"])
        if alias not in MANUAL_GATE_TASK_IDS:
            continue
        body = _decode_body(row)
        blocked_gates.append(
            {
                "task_id": alias,
                "status": str(row["status"]),
                "reason": str(body.get("blocked_reason") or ""),
                "authorization_verified": bool(
                    gate_authorization[alias]["authorization_verified"]
                ),
                "authorization_detail": str(
                    gate_authorization[alias]["detail"]
                ),
                "held_descendant_count": sum(
                    1
                    for held_alias in held_task_ids
                    if held_alias != alias
                ),
                "dependencies_satisfied": dependencies_by_task[
                    str(row["task_cid"])
                ].issubset(completed_cids),
            }
        )
    non_success_rows = tuple(
        row for row in tasks if str(row["status"]) not in {"completed", "skipped"}
    )
    manual_gate_wait_only = bool(non_success_rows) and all(
        str(row["task_alias"]) in MANUAL_GATE_TASK_IDS
        and str(row["status"]) == "blocked"
        for row in non_success_rows
    )
    runnable_nonterminal = tuple(
        row
        for row in non_success_rows
        if str(row["task_alias"]) not in held_task_ids
        and str(row["task_alias"]) not in MANUAL_GATE_TASK_IDS
    )
    authorization_wait = bool(hold_projection["incomplete_gate_task_ids"]) and not ready_task_ids and not runnable_nonterminal
    authorization_evidence_failed = any(
        gate["status"] == "completed" and not gate["authorization_verified"]
        for gate in blocked_gates
    )
    master_pid = _read_pid(MASTER_PID)
    master_alive, master_identity_reason = _master_process_status(
        master_pid,
        expected_plan_root=snapshot.plan_root_cid,
        expected_repository_root=snapshot.repository_tree_id,
    )
    candidate_master_identity = _read_master_identity()
    stored_master_identity = (
        candidate_master_identity
        if candidate_master_identity
        and candidate_master_identity.get("plan_root_cid") == snapshot.plan_root_cid
        and candidate_master_identity.get("repository_tree_id")
        == snapshot.repository_tree_id
        else None
    )
    expected_lane_count = _safe_int(
        (stored_master_identity or {}).get("lane_count")
    )
    lanes: list[dict[str, Any]] = []
    now = time.time()
    if STATE_ROOT.is_dir():
        for status_path in sorted(STATE_ROOT.glob("lane-*/*_supervisor_status.json")):
            lane_match = re.fullmatch(r"lane-(\d+)", status_path.parent.name)
            lane_index = int(lane_match.group(1)) if lane_match else -1
            if expected_lane_count and not 0 <= lane_index < expected_lane_count:
                continue
            payload = _read_json_object(status_path)
            lane_repo_root = Path(str(payload.get("repo_root") or REPO_ROOT))
            raw_state_path = Path(
                str(
                    payload.get("state_path")
                    or status_path.with_name(
                        status_path.name.replace(
                            "_supervisor_status.json", "_task_state.json"
                        )
                    )
                )
            )
            state_path = (
                raw_state_path
                if raw_state_path.is_absolute()
                else lane_repo_root / raw_state_path
            )
            state_payload = _read_json_object(state_path)
            log_value = str(payload.get("log_path") or "")
            raw_log_path = Path(log_value) if log_value else None
            log_path = (
                raw_log_path
                if raw_log_path is None or raw_log_path.is_absolute()
                else lane_repo_root / raw_log_path
            )
            active_log_value = str(state_payload.get("active_log_path") or "")
            raw_active_log_path = (
                Path(active_log_value) if active_log_value else None
            )
            active_log_path = (
                raw_active_log_path
                if raw_active_log_path is None or raw_active_log_path.is_absolute()
                else lane_repo_root / raw_active_log_path
            )
            max_attempts = _safe_int(payload.get("max_task_attempts"))
            attempt_limited, attempt_ledger_divergences = (
                _attempt_limit_projection(
                    state_payload,
                    task_alias_by_cid={
                        task_cid: str(row["task_alias"])
                        for task_cid, row in rows_by_cid.items()
                    },
                    eligible_task_aliases={
                        str(row["task_alias"])
                        for row in rows_by_cid.values()
                        if str(row["status"]) not in terminal_statuses
                    },
                    max_attempts=max_attempts,
                )
            )
            serialized_state = _canonical_json(state_payload)
            status_stat = status_path.stat()
            state_stat = state_path.stat() if state_path.is_file() else None
            log_stat = (
                log_path.stat()
                if log_path is not None and log_path.is_file()
                else None
            )
            active_log_stat = (
                active_log_path.stat()
                if active_log_path is not None and active_log_path.is_file()
                else None
            )
            daemon_pid = _safe_int(payload.get("daemon_pid")) or None
            daemon_identity = (
                _process_birth_identity(daemon_pid)
                if daemon_pid is not None
                else None
            )
            daemon_argv = tuple(
                str(item) for item in (daemon_identity or {}).get("argv") or ()
            )
            daemon_bound = bool(
                daemon_identity
                and "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon"
                in daemon_argv
                and _option_value(daemon_argv, "--todo-path")
                == str(DATABASE_PATH)
                and _option_value(daemon_argv, "--expected-task-source-root")
                == snapshot.plan_root_cid
                and _option_value(
                    daemon_argv, "--expected-task-source-repository-root"
                )
                == snapshot.repository_tree_id
                and _option_value(
                    daemon_argv,
                    "--duckdb-bootstrap-completion-evidence-id",
                )
                == bootstrap_completion_evidence_id
                and _option_value(daemon_argv, "--state-dir")
                == str(status_path.parent)
            )
            lanes.append(
                {
                    "lane_index": lane_index,
                    "path": str(status_path),
                    "age_seconds": round(max(0.0, now - status_stat.st_mtime), 1),
                    "status": str(payload.get("status") or "unknown"),
                    "daemon_pid": daemon_pid,
                    "daemon_alive": daemon_bound,
                    "daemon_identity_bound": daemon_bound,
                    "source_contract_bound": bool(
                        str(payload.get("repo_root") or "") == str(REPO_ROOT)
                        and str(payload.get("todo_path") or "")
                        == str(DATABASE_PATH)
                    ),
                    "restart_count": _safe_int(payload.get("restart_count")),
                    "active_worker_count": _safe_int(
                        payload.get("active_worker_count")
                    ),
                    "stalled_without_active_worker": bool(
                        payload.get("stalled_without_active_worker")
                    ),
                    "worker_phase_age_seconds": (
                        float(payload["worker_phase_age_seconds"])
                        if isinstance(
                            payload.get("worker_phase_age_seconds"),
                            (int, float),
                        )
                        else None
                    ),
                    "state_path": str(state_path),
                    "state_age_seconds": (
                        round(max(0.0, now - state_stat.st_mtime), 1)
                        if state_stat is not None
                        else None
                    ),
                    "heartbeat_age_seconds": _timestamp_age_seconds(
                        state_payload.get("heartbeat_at"), now=now
                    ),
                    "active_task_id": str(state_payload.get("active_task_id") or ""),
                    "active_phase": str(state_payload.get("active_phase") or ""),
                    "active_phase_age_seconds": _timestamp_age_seconds(
                        state_payload.get("active_phase_started_at"), now=now
                    ),
                    "selection_idle_reason": str(
                        state_payload.get("selection_idle_reason") or ""
                    ),
                    "attempt_limited_task_ids": attempt_limited,
                    "attempt_ledger_divergences": attempt_ledger_divergences,
                    "provider_capacity_signal": (
                        "provider_capacity_backoff" in serialized_state
                        or "provider_capacity_exhausted" in serialized_state
                    ),
                    "log_path": str(log_path) if log_path is not None else "",
                    "log_age_seconds": (
                        round(max(0.0, now - log_stat.st_mtime), 1)
                        if log_stat is not None
                        else None
                    ),
                    "log_size": (
                        int(log_stat.st_size)
                        if log_stat is not None
                        else 0
                    ),
                    "active_log_path": (
                        str(active_log_path)
                        if active_log_path is not None
                        else ""
                    ),
                    "active_log_age_seconds": (
                        round(max(0.0, now - active_log_stat.st_mtime), 1)
                        if active_log_stat is not None
                        else None
                    ),
                    "active_log_size": (
                        int(active_log_stat.st_size)
                        if active_log_stat is not None
                        else 0
                    ),
                    "activity_token": [
                        str(state_payload.get("active_task_id") or ""),
                        str(state_payload.get("active_phase") or ""),
                        str(state_payload.get("active_phase_detail") or ""),
                        (
                            int(active_log_stat.st_mtime_ns)
                            if active_log_stat is not None
                            else 0
                        ),
                        (
                            int(active_log_stat.st_size)
                            if active_log_stat is not None
                            else 0
                        ),
                        str(state_payload.get("last_implementation_finished_at") or ""),
                        str(state_payload.get("last_merge_finished_at") or ""),
                        str(state_payload.get("last_merge_commit") or ""),
                        _safe_int(state_payload.get("completed_count")),
                    ],
                }
            )
    retry_reset_inspection = _retry_reset_inspection()
    return {
        "program_id": PROGRAM_ID,
        "database": str(DATABASE_PATH),
        "plan_root_cid": snapshot.plan_root_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "projection_cid": snapshot.projection_cid,
        "revision": snapshot.revision,
        "event_cursor": snapshot.event_cursor,
        "task_count": len(tasks),
        "terminal_count": terminal,
        "successful_count": succeeded,
        "drained": terminal == len(tasks),
        "all_succeeded": succeeded == len(tasks),
        "terminal_failures": terminal_failures,
        "status_counts": dict(sorted(counts.items())),
        "ready_task_ids": ready_task_ids,
        "blocked_gates": blocked_gates,
        "manual_gate_wait_only": manual_gate_wait_only,
        "authorization_wait": authorization_wait,
        "authorization_evidence_failed": authorization_evidence_failed,
        "authorization_incomplete_gate_task_ids": list(
            hold_projection["incomplete_gate_task_ids"]
        ),
        "authorization_held_task_ids": list(hold_projection["held_task_aliases"]),
        "authorization_held_set_sha256": hold_projection["held_set_sha256"],
        "master_pid": master_pid,
        "master_process_exists": _pid_exists(master_pid),
        "master_alive": master_alive,
        "master_identity_reason": master_identity_reason,
        "master_log": str(MASTER_LOG),
        "expected_lane_count": expected_lane_count,
        "observed_lane_count": len(lanes),
        "lane_status": lanes,
        "retry_reset_inspection": retry_reset_inspection,
    }


def preflight_checks(*, require_clean: bool = True) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "required": required})

    validate_program()
    add("program_dag", True, f"{len(GOALS)} goals and {len(TASKS)} acyclic tasks")
    branch = _git("branch", "--show-current")
    add("target_branch", branch == TARGET_BRANCH, f"current={branch!r}; expected={TARGET_BRANCH!r}")
    dirty = _git("status", "--porcelain=v1")
    add(
        "clean_worktree",
        not dirty,
        "clean" if not dirty else "tracked/untracked changes remain: " + ", ".join(line[:120] for line in dirty.splitlines()[:8]),
        required=require_clean,
    )
    add("accelerate_submodule", (ACCELERATE_ROOT / ".git").exists(), str(ACCELERATE_ROOT))
    if (ACCELERATE_ROOT / ".git").exists():
        submodule_dirty = _git("-C", "ipfs_accelerate_py", "status", "--porcelain=v1")
        add(
            "accelerate_submodule_clean",
            not submodule_dirty,
            "clean" if not submodule_dirty else submodule_dirty.splitlines()[0],
        )
        try:
            gitlink_commit = _head_gitlink_commit("ipfs_accelerate_py")
            submodule_commit = _git("-C", "ipfs_accelerate_py", "rev-parse", "HEAD")
            add(
                "accelerate_gitlink_binding",
                gitlink_commit == submodule_commit,
                f"gitlink={gitlink_commit}; checkout={submodule_commit}",
            )
        except RuntimeError as exc:
            add("accelerate_gitlink_binding", False, str(exc))
    try:
        checkout_lock_detail = _retry_checkout_lock_preflight()
        add("retry_checkout_lock_authority", True, checkout_lock_detail)
    except (OSError, RuntimeError) as exc:
        add(
            "retry_checkout_lock_authority",
            False,
            f"{type(exc).__name__}: {exc}",
        )
    retry_reset_inspection = _retry_reset_inspection()
    add(
        "retry_reset_journal_recovery",
        bool(retry_reset_inspection["ok"]),
        (
            "clean"
            if retry_reset_inspection["ok"]
            else retry_reset_inspection["error"]
            or _canonical_json(retry_reset_inspection["incomplete"])
        ),
    )

    try:
        artifact_evidence = _bootstrap_artifact_evidence()
        lock_relative = BOOTSTRAP_REQUIREMENTS.relative_to(REPO_ROOT).as_posix()
        add(
            "bootstrap_requirements_policy",
            artifact_evidence.get(lock_relative) == BOOTSTRAP_REQUIREMENTS_SHA256,
            f"path={BOOTSTRAP_REQUIREMENTS}; digest={artifact_evidence.get(lock_relative)}",
        )
        validator_relative = BOOTSTRAP_VALIDATOR.relative_to(REPO_ROOT).as_posix()
        validator_lock_relative = BOOTSTRAP_VALIDATOR_REQUIREMENTS.relative_to(
            REPO_ROOT
        ).as_posix()
        add(
            "bootstrap_validator_artifacts",
            bool(
                artifact_evidence.get(validator_relative)
                == BOOTSTRAP_VALIDATOR_SHA256
                and artifact_evidence.get(validator_lock_relative)
                == BOOTSTRAP_VALIDATOR_REQUIREMENTS_SHA256
            ),
            f"module={artifact_evidence.get(validator_relative)}; "
            f"lock={artifact_evidence.get(validator_lock_relative)}",
        )
        validator_cache_receipt = _read_json_object(
            BOOTSTRAP_VALIDATOR_ROOT / "wheel-cache-receipt.json"
        )
        validator_cache_valid, validator_cache_detail = (
            _validate_bootstrap_validator_cache_receipt(
                validator_cache_receipt,
                verify_files=True,
            )
        )
        add(
            "bootstrap_validator_cache",
            validator_cache_valid,
            validator_cache_detail,
        )
        environment_probe = _run_environment_probe(_environment_python())
        version = str(environment_probe["duckdb_version"])
        parsed = _version_tuple(version)
        isolated_runtime = bool(
            environment_probe.get("environment_root") == str(EXPECTED_ENV_ROOT)
            and environment_probe.get("isolated_environment")
        )
        add(
            "isolated_execution_environment",
            isolated_runtime,
            f"sys.prefix={Path(sys.prefix).resolve()}; expected={EXPECTED_ENV_ROOT}",
        )
        live_runtime_valid, live_runtime_detail = _live_runtime_import_contract(
            environment_probe
        )
        add(
            "sealed_runtime_import_contract",
            live_runtime_valid,
            live_runtime_detail,
        )
        environment_receipt = _read_json_object(ENVIRONMENT_RECEIPT)
        environment_receipt_valid, environment_receipt_detail = (
            _validate_environment_receipt(environment_receipt, environment_probe)
        )
        add(
            "execution_environment_receipt",
            environment_receipt_valid,
            f"path={ENVIRONMENT_RECEIPT}; {environment_receipt_detail}",
        )
        add(
            "duckdb_local_task_source",
            parsed >= (1, 3, 2),
            f"installed={version}; minimum local=1.3.2",
        )
        add(
            "quack_runtime",
            parsed[:3] == REQUIRED_DUCKDB_VERSION,
            f"installed={version}; bootstrap pins 1.5.5; DQK-082 final attestation pending",
        )
        add(
            "duckdb_program_pin",
            parsed[:3] == REQUIRED_DUCKDB_VERSION,
            f"installed={version}; required={'.'.join(map(str, REQUIRED_DUCKDB_VERSION))}",
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        for name in (
            "bootstrap_requirements_policy",
            "bootstrap_validator_artifacts",
            "bootstrap_validator_cache",
            "isolated_execution_environment",
            "execution_environment_receipt",
            "duckdb_local_task_source",
            "quack_runtime",
            "duckdb_program_pin",
        ):
            if not any(check["name"] == name for check in checks):
                add(name, False, detail)

    expected_master_plan = ""
    expected_master_repository = ""
    source = _source(require=False)
    if source is None:
        add("control_database", False, f"missing {DATABASE_PATH}")
    else:
        try:
            integrity = source.validate_integrity()
            snapshot, projected, row_counts = _consistent_rows(
                source,
                ("goals", "tasks", "task_dependencies", "task_events"),
            )
            expected_master_plan = snapshot.plan_root_cid
            expected_master_repository = snapshot.repository_tree_id
            add("control_database", bool(integrity.valid), f"revision={snapshot.revision}; projection={snapshot.projection_cid}")
            expected_plan_root, expected_source_identity = _current_formal_identity(
                snapshot.repository_tree_id
            )
            task_aliases = {str(row["task_alias"]) for row in projected["tasks"]}
            expected_aliases = {str(task["task_id"]) for task in TASKS}
            exact_population = (
                snapshot.plan_root_cid == expected_plan_root
                and snapshot.source_identity == expected_source_identity
                and row_counts["goals"] == len(GOALS)
                and row_counts["tasks"] == len(TASKS)
                and row_counts["task_dependencies"]
                == sum(len(task.get("depends_on") or ()) for task in TASKS)
                and task_aliases == expected_aliases
            )
            add(
                "formal_source_database_parity",
                exact_population,
                f"db_plan={snapshot.plan_root_cid}; current_plan={expected_plan_root}; "
                f"goals={row_counts['goals']}/{len(GOALS)}; tasks={row_counts['tasks']}/{len(TASKS)}; "
                f"dependencies={row_counts['task_dependencies']}/"
                f"{sum(len(task.get('depends_on') or ()) for task in TASKS)}",
            )
            repository_ok, repository_detail = _repository_binding_is_launch_compatible(
                snapshot.repository_tree_id,
                source=source,
            )
            add(
                "repository_root_binding",
                repository_ok,
                f"admitted={snapshot.repository_tree_id}; checkout={_repository_tree_id()}; {repository_detail}",
            )
            manual_ok, manual_detail = _manual_gate_restart_admission(source)
            add(
                "manual_gate_authenticated_execution",
                manual_ok,
                manual_detail,
            )
            _hold_snapshot, hold_projection = _manual_gate_hold_projection(source)
            add(
                "manual_gate_descendant_hold",
                True,
                (
                    f"incomplete={','.join(hold_projection['incomplete_gate_task_ids']) or 'none'}; "
                    f"held={len(hold_projection['held_task_aliases'])}; "
                    f"digest={hold_projection['held_set_sha256']}"
                ),
            )
            (
                bridge_receipt_valid,
                bridge_receipt_detail,
                _bridge_evidence_id,
            ) = (
                _bootstrap_bridge_receipt_contract(
                    source,
                    snapshot,
                    projected["tasks"],
                    projected["task_events"],
                )
            )
            add(
                "bootstrap_bridge_receipt",
                bridge_receipt_valid,
                bridge_receipt_detail,
            )
            ready = source.ready_tasks(limit=1000)
            add("ready_work", bool(ready.tasks), f"ready={len(ready.tasks)}", required=False)
        except Exception as exc:
            add("control_database", False, f"{type(exc).__name__}: {exc}")

    try:
        _DuckDBTaskSource, providers = _accelerate_imports()
        grok_ready = bool(providers[0]())
        goose_ready = bool(providers[1]())
        codex_ready = bool(shlex.split(subprocess.run(["bash", "-lc", "command -v codex"], text=True, capture_output=True).stdout.strip()))
        add(
            "implementation_provider",
            grok_ready or goose_ready or codex_ready,
            f"grok_authenticated={grok_ready}; goose_meta_authenticated={goose_ready}; codex_installed={codex_ready}",
        )
    except Exception as exc:
        add("implementation_provider", False, f"{type(exc).__name__}: {exc}")

    master_pid = _read_pid(MASTER_PID)
    master_bound, master_reason = _master_process_status(
        master_pid,
        expected_plan_root=expected_master_plan,
        expected_repository_root=expected_master_repository,
    )
    master_exists = _pid_exists(master_pid)
    add(
        "runtime_namespace_free",
        not master_exists,
        (
            "free"
            if not master_exists
            else f"occupied pid={master_pid}; bound={master_bound}; reason={master_reason}"
        ),
    )
    return checks


def _print_checks(checks: Sequence[Mapping[str, Any]]) -> None:
    for check in checks:
        label = "PASS" if check["ok"] else ("WARN" if not check["required"] else "FAIL")
        print(f"{label:4} {check['name']}: {check['detail']}")


def _assert_supported_bootstrap_host() -> None:
    import platform

    if Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve():
        raise RuntimeError(
            "bootstrap-environment must run from the base interpreter, not a virtual environment"
        )
    if (
        sys.version_info[:2] != BOOTSTRAP_SUPPORTED_PYTHON
        or platform.python_implementation() != "CPython"
        or platform.system() != BOOTSTRAP_SUPPORTED_SYSTEM
        or platform.machine() not in BOOTSTRAP_SUPPORTED_MACHINES
    ):
        raise RuntimeError(
            "bootstrap host must be CPython 3.12 on supported Linux aarch64/x86_64"
        )


def _cmd_bootstrap_environment_locked(args: argparse.Namespace) -> int:
    """Create or exactly validate the bootstrap-only supervisor environment."""

    del args
    _assert_safe_bootstrap_target()
    _bootstrap_artifact_evidence()
    if EXPECTED_ENV_ROOT.exists():
        if not EXPECTED_ENV_ROOT.is_dir():
            raise RuntimeError(
                f"existing environment target is not a directory: {EXPECTED_ENV_ROOT}"
            )
        try:
            probe = _run_environment_probe(
                _environment_python(),
                _lifecycle_lock_held=True,
            )
            receipt = _read_json_object(ENVIRONMENT_RECEIPT)
            valid, detail = _validate_environment_receipt(receipt, probe)
        except Exception as exc:
            raise RuntimeError(
                "refusing to modify or recreate the existing environment; "
                f"archive it explicitly after review: {type(exc).__name__}: {exc}"
            ) from exc
        if not valid:
            raise RuntimeError(
                "refusing to modify or recreate the existing environment; "
                f"archive it explicitly after review: {detail}"
            )
        validator_receipt = _provision_bootstrap_validator()
        print(
            _canonical_json(
                {
                    "status": "already-valid",
                    "environment_root": str(EXPECTED_ENV_ROOT),
                    "receipt_id": receipt["receipt_id"],
                    "validator_cache_receipt_id": validator_receipt["receipt_id"],
                    "dqk_082_completed": False,
                }
            )
        )
        return 0

    _assert_supported_bootstrap_host()
    repository_before = _bootstrap_repository_evidence()
    EXPECTED_ENV_ROOT.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(EXPECTED_ENV_ROOT, mode=0o700)
    except FileExistsError as exc:
        raise RuntimeError(
            "environment target appeared during bootstrap; refusing to modify it"
        ) from exc
    builder = venv.EnvBuilder(
        system_site_packages=False,
        clear=False,
        symlinks=True,
        upgrade=False,
        with_pip=True,
        upgrade_deps=False,
    )
    builder.create(EXPECTED_ENV_ROOT)
    target_python = _environment_python()
    if not target_python.is_file():
        raise RuntimeError(f"venv creation did not produce {target_python}")
    artifact_root = EXPECTED_ENV_ROOT / "bootstrap-artifacts"
    artifact_root.mkdir(mode=0o700)
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("PYTHON") or key.startswith("LD_"):
            environment.pop(key)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    download = subprocess.run(
        _bootstrap_download_argv(),
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if download.returncode:
        raise RuntimeError(
            "hash-locked DuckDB download failed; the new environment was left "
            "in place for inspection and will not be mutated automatically: "
            + (
                download.stderr.strip()
                or download.stdout.strip()
                or f"exit {download.returncode}"
            )
        )
    install_argv = _bootstrap_install_argv()
    install = subprocess.run(
        install_argv,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if install.returncode:
        raise RuntimeError(
            "hash-locked DuckDB bootstrap failed; the new environment was left "
            "in place for inspection and will not be mutated automatically: "
            + (install.stderr.strip() or install.stdout.strip() or f"exit {install.returncode}")
        )
    remove_installer = subprocess.run(
        _bootstrap_remove_installer_argv(),
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if remove_installer.returncode:
        raise RuntimeError(
            "bootstrap installer removal failed; the new environment was left "
            "in place for inspection and will not be mutated automatically: "
            + (
                remove_installer.stderr.strip()
                or remove_installer.stdout.strip()
                or f"exit {remove_installer.returncode}"
            )
        )
    _write_sealed_python_launcher()
    probe = _run_environment_probe(
        target_python,
        _lifecycle_lock_held=True,
    )
    compatible, detail = _bootstrap_probe_compatible(probe)
    if not compatible:
        raise RuntimeError(f"created environment failed bootstrap policy: {detail}")
    repository_after = _bootstrap_repository_evidence()
    if repository_after != repository_before:
        raise RuntimeError("repository bootstrap evidence changed during environment creation")
    receipt = _environment_receipt_payload(probe, repository_after)
    _atomic_write_text(
        ENVIRONMENT_RECEIPT,
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    )
    persisted = _read_json_object(ENVIRONMENT_RECEIPT)
    valid, validation_detail = _validate_environment_receipt(persisted, probe)
    if not valid:
        raise RuntimeError(f"persisted environment receipt failed validation: {validation_detail}")
    validator_receipt = _provision_bootstrap_validator()
    print(
        _canonical_json(
            {
                "status": "created",
                "environment_root": str(EXPECTED_ENV_ROOT),
                "receipt_id": receipt["receipt_id"],
                "next_python": str(SEALED_PYTHON_LAUNCHER),
                "validator_cache_receipt_id": validator_receipt["receipt_id"],
                "dqk_082_completed": False,
            }
        )
    )
    return 0


def cmd_bootstrap_environment(args: argparse.Namespace) -> int:
    """Provision or verify the environment under its exclusive owner lock."""

    with _environment_lifecycle_lock(exclusive=True):
        return _cmd_bootstrap_environment_locked(args)


def _bootstrap_validator_provision_argv() -> tuple[str, ...]:
    return (
        str(_trusted_base_python_path()),
        "-I",
        "-B",
        "-S",
        str(BOOTSTRAP_VALIDATOR),
        "provision",
        "--validator-root",
        str(BOOTSTRAP_VALIDATOR_ROOT),
        "--lock",
        str(BOOTSTRAP_VALIDATOR_REQUIREMENTS),
    )


def _bootstrap_bridge_validation_argv() -> tuple[str, ...]:
    argv = [
        str(_trusted_base_python_path()),
        "-I",
        "-B",
        "-S",
        str(BOOTSTRAP_VALIDATOR),
        "run",
        "--parent-root",
        str(REPO_ROOT),
        "--accelerate-root",
        str(ACCELERATE_ROOT),
        "--runtime-root",
        str(EXPECTED_ENV_ROOT),
        "--validator-root",
        str(BOOTSTRAP_VALIDATOR_ROOT),
        "--base-python",
        str(_trusted_base_python_path()),
        "--lock",
        str(BOOTSTRAP_VALIDATOR_REQUIREMENTS),
    ]
    for test_path in BOOTSTRAP_BRIDGE_VALIDATION_TESTS:
        argv.extend(("--test", test_path))
    return tuple(argv)


def _validator_subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if (
            key.startswith("PYTHON")
            or key.startswith("PYTEST")
            or key.startswith("LD_")
            or key.startswith("COV_CORE_")
            or key.startswith("COVERAGE_")
            or key.startswith("IPFS_ACCELERATE_AGENT_VALIDATION_")
            or key.startswith("IPFS_DATASETS_DQK_VALIDATION_")
        ):
            environment.pop(key)
    environment.update(
        {
            "IPFS_ACCEL_IMPORT_EAGER": "0",
            "IPFS_ACCEL_SKIP_CORE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return environment


def _content_bound_validator_payload(payload: Any, *, schema: str) -> tuple[bool, str]:
    if not isinstance(payload, Mapping) or payload.get("schema") != schema:
        return False, "validator payload schema mismatch"
    receipt_id = str(payload.get("receipt_id") or "")
    material = dict(payload)
    material.pop("receipt_id", None)
    expected = f"sha256:{hashlib.sha256(_canonical_json(material).encode('utf-8')).hexdigest()}"
    if receipt_id != expected:
        return False, "validator payload receipt ID is not content-bound"
    return True, receipt_id


def _strict_validator_stdout(stdout: str, stderr: str, *, noun: str) -> dict[str, Any]:
    if len(stdout.encode("utf-8")) > 2 * 1024 * 1024 or len(
        stderr.encode("utf-8")
    ) > 256 * 1024:
        raise RuntimeError(f"{noun} output exceeded its byte bound")
    if stderr.strip():
        raise RuntimeError(f"{noun} wrote unexpected stderr: {stderr.splitlines()[-1]}")
    payload = _strict_json_object(stdout, noun=noun)
    return payload


def _provision_bootstrap_validator() -> dict[str, Any]:
    argv = _bootstrap_validator_provision_argv()
    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=_validator_subprocess_environment(),
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError(
            "hash-locked validator provisioning failed: "
            + (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")
        )
    payload = _strict_validator_stdout(
        result.stdout, result.stderr, noun="validator provisioning receipt"
    )
    valid, detail = _content_bound_validator_payload(
        payload,
        schema="ipfs_datasets_py/duckdb-quack-validator-wheel-cache@1",
    )
    cache_valid, cache_detail = _validate_bootstrap_validator_cache_receipt(
        payload,
        verify_files=True,
    )
    if not valid or not cache_valid:
        raise RuntimeError(
            "validator provisioning receipt is invalid: "
            + (detail if not valid else cache_detail)
        )
    return payload


def _validate_bootstrap_validator_cache_receipt(
    payload: Any,
    *,
    verify_files: bool,
) -> tuple[bool, str]:
    valid, detail = _content_bound_validator_payload(
        payload,
        schema="ipfs_datasets_py/duckdb-quack-validator-wheel-cache@1",
    )
    if not valid or not isinstance(payload, Mapping):
        return False, detail
    wheels = payload.get("wheels")
    wheel_paths = payload.get("wheel_paths")
    if (
        payload.get("validator_root") != str(BOOTSTRAP_VALIDATOR_ROOT)
        or payload.get("lock_path")
        != str(BOOTSTRAP_VALIDATOR_REQUIREMENTS.resolve())
        or payload.get("lock_sha256")
        != BOOTSTRAP_VALIDATOR_REQUIREMENTS_SHA256
        or not isinstance(wheels, list)
        or not isinstance(wheel_paths, list)
        or len(wheels) != 5
        or len(wheel_paths) != 5
        or {str(item.get("package") or "") for item in wheels if isinstance(item, Mapping)}
        != {"iniconfig", "packaging", "pluggy", "pygments", "pytest"}
    ):
        return False, "validator cache receipt contract mismatch"
    if verify_files:
        observed_paths: set[str] = set()
        for item in wheels:
            if not isinstance(item, Mapping):
                return False, "validator cache wheel evidence is malformed"
            path = Path(str(item.get("path") or ""))
            try:
                path.resolve(strict=True).relative_to(
                    (BOOTSTRAP_VALIDATOR_ROOT / "wheels").resolve(strict=True)
                )
            except (OSError, ValueError):
                return False, "validator cache wheel escapes its exact root"
            if (
                path.is_symlink()
                or not path.is_file()
                or _sha256_file(path) != item.get("archive_sha256")
            ):
                return False, "validator cache wheel bytes changed"
            observed_paths.add(str(path.absolute()))
        if observed_paths != {str(Path(item).absolute()) for item in wheel_paths}:
            return False, "validator cache wheel path projection mismatch"
    return True, str(payload.get("receipt_id") or "")


def _task_validation_python_attestation() -> dict[str, Any]:
    """Re-derive the one validation interpreter admitted to DQK workers.

    The generic accelerator runtime correctly rejects executables below a
    user-writable ancestor.  DQK has a stronger, program-specific boundary:
    every sealed supervisor process retains the shared environment lifecycle
    lock, while the exclusive provisioner publishes an exact wrapper and five
    hash-locked wheels.  Re-read both artifacts without following symlinks and
    bind the wrapper bytes before installing the in-process adapter.
    """

    import stat

    wrapper_raw = _read_nofollow_bounded_file(
        TASK_VALIDATION_PYTHON,
        max_bytes=256 * 1024,
    )
    try:
        wrapper_metadata = TASK_VALIDATION_PYTHON.lstat()
    except OSError as exc:
        raise RuntimeError("task-validation Python metadata is unavailable") from exc
    wrapper_sha256 = f"sha256:{hashlib.sha256(wrapper_raw).hexdigest()}"
    validator_policy_raw = _read_nofollow_bounded_file(
        BOOTSTRAP_VALIDATOR,
        max_bytes=2 * 1024 * 1024,
    )
    validator_lock_raw = _read_nofollow_bounded_file(
        BOOTSTRAP_VALIDATOR_REQUIREMENTS,
        max_bytes=256 * 1024,
    )
    if (
        not stat.S_ISREG(wrapper_metadata.st_mode)
        or TASK_VALIDATION_PYTHON.is_symlink()
        or wrapper_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(wrapper_metadata.st_mode) != 0o500
        or wrapper_sha256 != TASK_VALIDATION_PYTHON_SHA256
        or f"sha256:{hashlib.sha256(validator_policy_raw).hexdigest()}"
        != BOOTSTRAP_VALIDATOR_SHA256
        or f"sha256:{hashlib.sha256(validator_lock_raw).hexdigest()}"
        != BOOTSTRAP_VALIDATOR_REQUIREMENTS_SHA256
    ):
        raise RuntimeError("task-validation Python attestation mismatch")

    cache_raw = _read_nofollow_bounded_file(
        BOOTSTRAP_VALIDATOR_ROOT / "wheel-cache-receipt.json",
        max_bytes=512 * 1024,
    )
    cache_receipt = _strict_json_object(
        cache_raw.decode("utf-8", errors="strict"),
        noun="task-validation wheel-cache receipt",
    )
    cache_valid, cache_detail = _validate_bootstrap_validator_cache_receipt(
        cache_receipt,
        verify_files=True,
    )
    if (
        not cache_valid
        or cache_receipt.get("receipt_id") != TASK_VALIDATOR_CACHE_RECEIPT_ID
    ):
        raise RuntimeError(
            "task-validation wheel cache is not admitted: " + cache_detail
        )
    return {
        "path": str(TASK_VALIDATION_PYTHON),
        "sha256": wrapper_sha256,
        "dispatch_source_sha256": TASK_VALIDATION_DISPATCH_SHA256,
        "size": wrapper_metadata.st_size,
        "mode": stat.S_IMODE(wrapper_metadata.st_mode),
        "validator_receipt_id": TASK_VALIDATOR_RECEIPT_ID,
        "cache_receipt_id": TASK_VALIDATOR_CACHE_RECEIPT_ID,
        "toolchain_id": _task_validation_toolchain_id(),
    }


def _install_task_validation_runtime_adapter() -> None:
    """Admit only the receipt-bound DQK pytest wrapper in this process."""

    attestation = _task_validation_python_attestation()
    if (
        os.environ.get("IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON")
        != str(TASK_VALIDATION_PYTHON)
        or os.environ.get("IPFS_DATASETS_DQK_VALIDATION_TOOLCHAIN_ID")
        != attestation["toolchain_id"]
    ):
        raise RuntimeError("task-validation environment binding mismatch")
    module = _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.validation_runtime",
        "ipfs_accelerate_py.agent_supervisor.validation_runtime",
    )
    current = module.validation_python_executable
    if getattr(current, "__dqk_task_validator_adapter__", False):
        if getattr(current, "__dqk_task_validator_sha256__", "") != attestation[
            "sha256"
        ]:
            raise RuntimeError("task-validation adapter identity changed")
        return

    original_file_identity = module._file_identity
    wrapper = TASK_VALIDATION_PYTHON

    def validation_python_executable(
        environment: Mapping[str, object] | None = None,
    ) -> str:
        source = os.environ if environment is None else environment
        if (
            str(source.get("IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON") or "")
            != str(wrapper)
            or os.environ.get("IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON")
            != str(wrapper)
        ):
            raise module.ValidationRuntimeError(
                "DQK task validation lost its sealed interpreter binding"
            )
        current_attestation = _task_validation_python_attestation()
        if current_attestation != attestation:
            raise module.ValidationRuntimeError(
                "DQK task-validation interpreter changed after admission"
            )
        return str(wrapper)

    validation_python_executable.__dqk_task_validator_adapter__ = True
    validation_python_executable.__dqk_task_validator_sha256__ = attestation[
        "sha256"
    ]

    def file_identity(path: Path) -> dict[str, object]:
        try:
            selected = Path(path).absolute()
        except (OSError, TypeError, ValueError):
            selected = Path(path)
        if selected != wrapper.absolute():
            return original_file_identity(path)
        current_attestation = _task_validation_python_attestation()
        if current_attestation != attestation:
            raise module.ValidationRuntimeError(
                "DQK task-validation interpreter changed after admission"
            )
        return {
            "path": str(wrapper),
            "sha256": str(attestation["sha256"]).removeprefix("sha256:"),
            "size": attestation["size"],
            "mode": attestation["mode"],
        }

    file_identity.__dqk_task_validator_adapter__ = True
    module.validation_python_executable = validation_python_executable
    module._file_identity = file_identity


def _validate_bootstrap_validator_receipt(
    receipt: Any,
    *,
    require_current_checkout: bool,
) -> tuple[bool, str]:
    valid, detail = _content_bound_validator_payload(
        receipt,
        schema="ipfs_datasets_py/duckdb-quack-validation-receipt@1",
    )
    if not valid or not isinstance(receipt, Mapping):
        return False, detail
    before = receipt.get("repository_before")
    after = receipt.get("repository_after")
    parent = before.get("parent") if isinstance(before, Mapping) else None
    accelerator = before.get("accelerator") if isinstance(before, Mapping) else None
    lock = receipt.get("lock")
    output = receipt.get("output")
    invocation = receipt.get("canonical_invocation")
    base = receipt.get("base_python")
    duckdb_runtime = receipt.get("duckdb_runtime")
    archive = (
        duckdb_runtime.get("archive")
        if isinstance(duckdb_runtime, Mapping)
        else None
    )
    artifacts = receipt.get("validation_artifacts")
    subprocess_wrapper = receipt.get("subprocess_wrapper")
    pytest_args = invocation.get("pytest_args") if isinstance(invocation, Mapping) else None
    expected_artifacts = {
        ("parent", BOOTSTRAP_VALIDATOR.relative_to(REPO_ROOT).as_posix()),
        (
            "parent",
            BOOTSTRAP_VALIDATOR_REQUIREMENTS.relative_to(REPO_ROOT).as_posix(),
        ),
        *(("accelerator", path) for path in BOOTSTRAP_BRIDGE_VALIDATION_TESTS),
    }
    observed_artifacts = {
        (str(item.get("repository_role") or ""), str(item.get("path") or ""))
        for item in artifacts
        if isinstance(item, Mapping)
    } if isinstance(artifacts, list) else set()
    allowed_duckdb_hashes = _bootstrap_allowed_wheel_hashes()
    try:
        task_validation_attestation = _task_validation_python_attestation()
    except (RuntimeError, OSError, UnicodeError) as exc:
        return False, f"task-validation interpreter is not admitted: {exc}"
    # Do not pin receipt_id to TASK_VALIDATOR_RECEIPT_ID: every successful
    # bridge run rebinds parent HEAD/tree, so the content-addressed receipt_id
    # changes. Structural checks below (wrapper attestation, artifacts, lock,
    # duckdb archive, success status) are the live contract. The constant remains
    # as toolchain metadata only.
    if (
        before != after
        or not isinstance(parent, Mapping)
        or not isinstance(accelerator, Mapping)
        or parent.get("root") != str(REPO_ROOT.resolve())
        or accelerator.get("root") != str(ACCELERATE_ROOT.resolve())
        or parent.get("accelerator_gitlink") != accelerator.get("head")
        or not isinstance(lock, Mapping)
        or lock.get("path") != str(BOOTSTRAP_VALIDATOR_REQUIREMENTS.resolve())
        or lock.get("sha256") != BOOTSTRAP_VALIDATOR_REQUIREMENTS_SHA256
        or not isinstance(output, Mapping)
        or _safe_int(output.get("returncode"), -1) != 0
        or not isinstance(invocation, Mapping)
        or not isinstance(pytest_args, list)
        or any(path not in pytest_args for path in BOOTSTRAP_BRIDGE_VALIDATION_TESTS)
        or not isinstance(base, Mapping)
        or base.get("executable") != str(_trusted_base_python_path())
        or not isinstance(archive, Mapping)
        or archive.get("archive_sha256") not in allowed_duckdb_hashes
        or not isinstance(subprocess_wrapper, Mapping)
        or subprocess_wrapper.get("path")
        != task_validation_attestation["path"]
        or subprocess_wrapper.get("sha256")
        != task_validation_attestation["sha256"]
        or subprocess_wrapper.get("dispatch_source_sha256")
        != task_validation_attestation["dispatch_source_sha256"]
        or observed_artifacts != expected_artifacts
        or any(
            item.get("blob_sha256") != item.get("working_sha256")
            for item in artifacts
            if isinstance(item, Mapping)
        )
    ):
        return False, "validator receipt contract mismatch"
    if require_current_checkout:
        try:
            current = {
                "parent_head": _git("rev-parse", "HEAD"),
                "parent_tree": _git("rev-parse", "HEAD^{tree}"),
                "accelerator_head": _git(
                    "-C", "ipfs_accelerate_py", "rev-parse", "HEAD"
                ),
                "accelerator_tree": _git(
                    "-C", "ipfs_accelerate_py", "rev-parse", "HEAD^{tree}"
                ),
            }
        except RuntimeError as exc:
            return False, str(exc)
        if current != {
            "parent_head": parent.get("head"),
            "parent_tree": parent.get("tree"),
            "accelerator_head": accelerator.get("head"),
            "accelerator_tree": accelerator.get("tree"),
        }:
            return False, "validator receipt does not bind the current checkouts"
    return True, str(receipt.get("receipt_id") or "")


def cmd_bootstrap(args: argparse.Namespace) -> int:
    _prepare_retry_reset_bootstrap_runtime_root()
    DuckDBTaskSource, _providers = _accelerate_imports()
    repository_tree = _repository_tree_id()
    source = DuckDBTaskSource(DATABASE_PATH)
    receipt = source.materialize(
        formal_source(repository_tree),
        repository_tree_id=repository_tree,
        expected_absent=bool(args.expected_absent),
    )
    integrity = source.validate_integrity()
    if not integrity.valid:
        raise RuntimeError("materialized DuckDB control database failed integrity validation")
    retry_reset_authority = _install_retry_reset_bootstrap_authority(source)
    retry_reset_inspection = _retry_reset_inspection()
    if not retry_reset_inspection["ok"]:
        raise RuntimeError(
            "installed retry-reset authority failed closed inspection: "
            + (
                str(retry_reset_inspection["error"])
                or _canonical_json(retry_reset_inspection["incomplete"])
            )
        )
    print(
        _canonical_json(
            {
                "receipt": dict(receipt),
                "integrity": True,
                "database": str(DATABASE_PATH),
                "retry_reset_authority": retry_reset_authority,
            }
        )
    )
    return 0


def cmd_ack_bootstrap(args: argparse.Namespace) -> int:
    source = _source()
    task = source.get_task(BOOTSTRAP_TASK_ID)
    if task is None:
        raise RuntimeError(f"missing bootstrap task {BOOTSTRAP_TASK_ID}")
    already_completed = task.status == "completed"
    if not already_completed and task.status not in {
        "pending",
        "ready",
        "admitted",
        "proposed",
    }:
        raise RuntimeError(f"cannot acknowledge {BOOTSTRAP_TASK_ID} from status {task.status}")
    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            REQUIRED_ACCELERATE_BRIDGE_COMMIT,
            "HEAD",
        ],
        cwd=ACCELERATE_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if ancestry.returncode != 0:
        raise RuntimeError(
            "accelerator submodule does not contain the required supervisor bridge "
            f"commit {REQUIRED_ACCELERATE_BRIDGE_COMMIT}"
        )
    submodule_dirty = _git("-C", "ipfs_accelerate_py", "status", "--porcelain=v1")
    if submodule_dirty:
        raise RuntimeError("accelerator submodule must be clean before bootstrap acknowledgement")
    submodule_commit = _git("-C", "ipfs_accelerate_py", "rev-parse", "HEAD")
    if _head_gitlink_commit("ipfs_accelerate_py") != submodule_commit:
        raise RuntimeError("superproject HEAD must pin the validated accelerator commit")
    validation_argv = _bootstrap_bridge_validation_argv()
    started = time.monotonic()
    validation = subprocess.run(
        validation_argv,
        cwd=REPO_ROOT,
        env=_validator_subprocess_environment(),
        text=True,
        capture_output=True,
        check=False,
        timeout=900,
    )
    output = validation.stdout + validation.stderr
    if validation.returncode != 0:
        raise RuntimeError(
            "required supervisor bridge validation failed: "
            + "\n".join(output.splitlines()[-20:])
        )
    validator_receipt = _strict_validator_stdout(
        validation.stdout,
        validation.stderr,
        noun="supervisor bridge validator receipt",
    )
    validator_receipt_valid, validator_receipt_detail = (
        _validate_bootstrap_validator_receipt(
            validator_receipt,
            require_current_checkout=True,
        )
    )
    if not validator_receipt_valid:
        raise RuntimeError(
            "required supervisor bridge validator receipt failed closed: "
            + validator_receipt_detail
        )
    submodule_tree = _git("-C", "ipfs_accelerate_py", "rev-parse", "HEAD^{tree}")
    snapshot = source.snapshot()
    task_source_identity_id = _repository_task_source_identity(source, snapshot)[
        "identity_id"
    ]
    if already_completed:
        _event_snapshot, event_tables, _event_counts = _consistent_rows(
            source,
            ("task_events",),
        )
        stored_receipt = _latest_status_receipt(
            event_tables["task_events"],
            task_cid=task.task_cid,
            status="completed",
        )
        stored_validation = (
            stored_receipt.get("validation")
            if isinstance(stored_receipt, Mapping)
            else None
        )
        stored_validator_receipt = (
            stored_validation.get("validator_receipt")
            if isinstance(stored_validation, Mapping)
            else None
        )
        stored_validator_valid, _stored_validator_detail = (
            _validate_bootstrap_validator_receipt(
                stored_validator_receipt,
                require_current_checkout=False,
            )
        )
        stored_superproject_commit = str(
            (stored_receipt or {}).get("superproject_commit") or ""
        )
        stored_submodule_commit = str(
            (stored_receipt or {}).get("submodule_commit") or ""
        )
        stable_receipt_valid = bool(
            stored_receipt
            and stored_receipt.get("schema")
            == "ipfs_datasets_py/duckdb-quack-bootstrap-receipt@1"
            and stored_receipt.get("kind") == "bootstrap_implementation_receipt"
            and stored_receipt.get("task_cid") == task.task_cid
            and stored_receipt.get("task_source_identity_id")
            == task_source_identity_id
            and stored_receipt.get("plan_root_cid") == snapshot.plan_root_cid
            and stored_receipt.get("repository_tree_id")
            == snapshot.repository_tree_id
            and stored_receipt.get("required_bridge_commit")
            == REQUIRED_ACCELERATE_BRIDGE_COMMIT
            and isinstance(stored_validation, Mapping)
            and stored_validation.get("argv") == list(validation_argv)
            and _safe_int(stored_validation.get("exit_status"), -1) == 0
            and stored_validator_valid
            and stored_validation.get("validator_receipt_id")
            == stored_validator_receipt.get("receipt_id")
            and re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                str(stored_validation.get("output_sha256") or ""),
            )
            is not None
            and stored_submodule_commit
            and stored_superproject_commit
        )
        for commit, cwd in (
            (stored_submodule_commit, ACCELERATE_ROOT),
            (stored_superproject_commit, REPO_ROOT),
        ):
            if stable_receipt_valid:
                stable_receipt_valid = (
                    subprocess.run(
                        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                        cwd=cwd,
                        text=True,
                        capture_output=True,
                        check=False,
                    ).returncode
                    == 0
                )
        if stable_receipt_valid:
            stable_receipt_valid = bool(
                _git("rev-parse", f"{stored_superproject_commit}^{{tree}}")
                == stored_receipt.get("superproject_tree")
                and _git(
                    "-C",
                    "ipfs_accelerate_py",
                    "rev-parse",
                    f"{stored_submodule_commit}^{{tree}}",
                )
                == stored_receipt.get("submodule_tree")
            )
        if not stable_receipt_valid:
            raise RuntimeError(
                f"{BOOTSTRAP_TASK_ID} completed receipt does not match the "
                "current database, Git history, or validation contract"
            )
        print(
            _canonical_json(
                {
                    "task": task.task_id,
                    "status": task.status,
                    "revalidated": True,
                    "stored_validation_output_sha256": stored_validation[
                        "output_sha256"
                    ],
                }
            )
        )
        return 0
    receipt = {
        "schema": "ipfs_datasets_py/duckdb-quack-bootstrap-receipt@1",
        "kind": "bootstrap_implementation_receipt",
        "task_cid": task.task_cid,
        "task_source_identity_id": task_source_identity_id,
        "plan_root_cid": snapshot.plan_root_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "superproject_commit": _git("rev-parse", "HEAD"),
        "superproject_tree": _git("rev-parse", "HEAD^{tree}"),
        "submodule_commit": submodule_commit,
        "submodule_tree": submodule_tree,
        "required_bridge_commit": REQUIRED_ACCELERATE_BRIDGE_COMMIT,
        "validation": {
            "argv": list(validation_argv),
            "exit_status": validation.returncode,
            "output_sha256": f"sha256:{hashlib.sha256(output.encode('utf-8')).hexdigest()}",
            "validator_receipt_id": validator_receipt["receipt_id"],
            "validator_receipt": validator_receipt,
            # DuckDB task-source receipts use the formal canonical JSON
            # contract, which deliberately rejects binary floating-point
            # values. Preserve the bounded timing observation as decimal text.
            "duration_seconds": f"{time.monotonic() - started:.3f}",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    result = source.compare_and_set_status(
        BOOTSTRAP_TASK_ID,
        expected_revision=task.revision,
        status="completed",
        receipt=receipt,
    )
    print(_canonical_json({"task": result.task.task_id, "status": result.task.status, "receipt_cid": result.receipt_cid}))
    return 0


def _manual_gate_receipt_id(namespace: str, value: Mapping[str, Any]) -> str:
    material = dict(value)
    for key in ("receipt_id", "execution_id", "journal_cid", "release_id"):
        material.pop(key, None)
    return f"sha256:{_sha256_text(_canonical_json({'namespace': namespace, 'value': material}))}"


def _read_nofollow_bounded_file(
    path: Path,
    *,
    max_bytes: int = 2 * 1024 * 1024,
) -> bytes:
    """Read one regular file while rejecting links in every path component."""

    import stat

    if isinstance(max_bytes, bool) or not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise RuntimeError("manual-gate file bound is invalid")
    absolute = Path(os.path.abspath(os.fspath(path)))
    components = absolute.parts
    if not components or components[0] != os.path.sep:
        raise RuntimeError("manual-gate input path must resolve from the filesystem root")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_fd = os.open(os.path.sep, directory_flags)
    descriptor: int | None = None
    try:
        for component in components[1:-1]:
            if component in {"", ".", ".."}:
                raise RuntimeError("manual-gate input path contains an unsafe component")
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        name = components[-1]
        if name in {"", ".", ".."}:
            raise RuntimeError("manual-gate input filename is invalid")
        descriptor = os.open(name, file_flags, dir_fd=directory_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= max_bytes:
            raise RuntimeError(
                f"manual-gate input must be a regular file containing 1..{max_bytes} bytes"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or len(raw) > max_bytes
        ):
            raise RuntimeError("manual-gate input changed during immutable capture")
        return raw
    except OSError as exc:
        raise RuntimeError("manual-gate input path is unavailable without symlinks") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _manual_gate_input_capture(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_nofollow_bounded_file(path)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError("manual-gate input is not UTF-8") from exc
    payload = _strict_json_object(text, noun="manual-gate input")
    capture = {
        "schema": "ipfs_datasets_py/manual-gate-immutable-input@2",
        "byte_length": len(raw),
        "sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}",
        "canonical_json_sha256": f"sha256:{_sha256_text(_canonical_json(payload))}",
    }
    return capture, raw


def _manual_gate_blob_store() -> Any:
    return manual_gate_authority.ContentBlobStore(MANUAL_GATE_LIFECYCLE_ROOT)


def _manual_gate_bound_input_capture(
    capture: Mapping[str, Any], raw: bytes
) -> dict[str, Any]:
    if set(capture) != {
        "schema",
        "byte_length",
        "sha256",
        "canonical_json_sha256",
    }:
        raise RuntimeError("manual-gate input capture shape is unsupported")
    if (
        capture.get("schema") != "ipfs_datasets_py/manual-gate-immutable-input@2"
        or capture.get("byte_length") != len(raw)
        or capture.get("sha256")
        != f"sha256:{hashlib.sha256(raw).hexdigest()}"
    ):
        raise RuntimeError("manual-gate input capture is detached from exact bytes")
    bound = dict(capture)
    bound["blob"] = _manual_gate_blob_store().put("input", raw)
    return bound


def _manual_gate_read_bound_input(capture: Mapping[str, Any]) -> bytes:
    if set(capture) != {
        "schema",
        "byte_length",
        "sha256",
        "canonical_json_sha256",
        "blob",
    } or not isinstance(capture.get("blob"), Mapping):
        raise RuntimeError("manual-gate persisted input capture shape is unsupported")
    raw = _manual_gate_blob_store().read(capture["blob"], expected_kind="input")
    payload = manual_gate_authority.strict_json_object(raw, noun="manual-gate input blob")
    if (
        capture.get("schema") != "ipfs_datasets_py/manual-gate-immutable-input@2"
        or capture.get("byte_length") != len(raw)
        or capture.get("sha256") != f"sha256:{hashlib.sha256(raw).hexdigest()}"
        or capture.get("canonical_json_sha256")
        != f"sha256:{_sha256_text(_canonical_json(payload))}"
    ):
        raise RuntimeError("manual-gate input blob does not match its capture")
    return raw


def _manual_gate_profile(task_id: str) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {
        RELEASE_GATE_TASK_ID: {
            "owner_task_id": RELEASE_VERIFIER_TASK_ID,
            "verifier_path": "scripts/validation/validate_accelerate_duckdb_quack_release.py",
            "invocation": "script",
            "prefix": (),
            "suffix": ("--accelerate-root", str(ACCELERATE_ROOT), "--json"),
            "output_schema": _RELEASE_VERIFICATION_SCHEMA,
        },
        REFINEMENT_GATE_TASK_ID: {
            "owner_task_id": "DQK-080",
            "verifier_path": "ipfs_datasets_py/duckdb_control/inventory_refinement.py",
            "invocation": "module",
            "module": "ipfs_datasets_py.duckdb_control.inventory_refinement",
            "prefix": ("verify",),
            "suffix": ("--json",),
            "output_schema": "ipfs_datasets_py/duckdb-control/inventory-refinement-verification@1",
        },
        PROMOTION_GATE_TASK_ID: {
            "owner_task_id": "DQK-100",
            "verifier_path": "ipfs_datasets_py/ducklake/cutover.py",
            "invocation": "module",
            "module": "ipfs_datasets_py.ducklake.cutover",
            "prefix": ("execute-promotion",),
            "suffix": ("--json",),
            "output_schema": "ipfs_datasets_py/ducklake-promotion-execution@1",
        },
        RUNTIME_ACTIVATION_GATE_TASK_ID: {
            "owner_task_id": "DQK-083",
            "verifier_path": "scripts/ops/ipfs_datasets_duckdb_quack_lifecycle.py",
            "invocation": "script",
            "prefix": ("activate-runtime",),
            "suffix": ("--json",),
            "output_schema": "ipfs_datasets_py/duckdb-quack-runtime-activation@1",
        },
    }
    try:
        return dict(profiles[task_id])
    except KeyError as exc:
        raise RuntimeError(f"unsupported manual gate {task_id}") from exc


def _manual_gate_verifier_attestation(task_id: str) -> dict[str, Any]:
    profile = _manual_gate_profile(task_id)
    relative_path = str(profile["verifier_path"])
    commit = _git("rev-parse", "HEAD").lower()
    tree = _git("rev-parse", "HEAD^{tree}").lower()
    working_path = REPO_ROOT / relative_path
    try:
        blob = _git_blob(commit, relative_path, maximum_bytes=2 * 1024 * 1024)
        working = _read_nofollow_bounded_file(working_path)
    except RuntimeError as exc:
        raise RuntimeError(
            f"manual_gate_verifier_not_materialized:{task_id}:{relative_path}"
        ) from exc
    if working != blob:
        raise RuntimeError("manual-gate verifier does not match its committed Git blob")
    return {
        "repository_commit": commit,
        "repository_tree": tree,
        "path": relative_path,
        "git_blob_sha256": f"sha256:{hashlib.sha256(blob).hexdigest()}",
        "byte_length": len(blob),
        "invocation": str(profile["invocation"]),
        "module": str(profile.get("module") or ""),
    }


def _manual_gate_task_authority_adapter(task_id: str) -> Any:
    """Return a task-owned signed-decision verifier, once its task ships it.

    The sealed bootstrap environment intentionally has no general-purpose
    cryptography dependency.  Trusting the verifier subprocess's own hashes
    would be circular, so the generic owner fails closed until the producing
    task installs a pinned adapter that can independently rederive the signed
    decision from the immutable input/output blobs.
    """

    if task_id in {PROMOTION_GATE_TASK_ID, RUNTIME_ACTIVATION_GATE_TASK_ID}:
        raise RuntimeError(
            f"manual_gate_effect_adapter_not_materialized:{task_id}"
        )
    raise RuntimeError(
        f"manual_gate_signature_adapter_not_materialized:{task_id}"
    )


def _manual_gate_interpreter_attestation() -> dict[str, Any]:
    import stat

    launcher = SEALED_PYTHON_LAUNCHER
    try:
        metadata = launcher.lstat()
    except OSError as exc:
        raise RuntimeError("sealed manual-gate Python launcher is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or launcher.is_symlink():
        raise RuntimeError("sealed manual-gate Python launcher is not a regular file")
    environment_probe = _run_environment_probe(_environment_python())
    environment_receipt = _read_json_object(ENVIRONMENT_RECEIPT)
    valid, detail = _validate_environment_receipt(
        environment_receipt, environment_probe
    )
    if not valid:
        raise RuntimeError(f"manual-gate interpreter receipt is invalid: {detail}")
    return {
        "launcher_path": str(launcher.absolute()),
        "launcher_sha256": _sha256_file(launcher),
        "base_python_path": str(_trusted_base_python_path()),
        "base_python_sha256": _sha256_file(_trusted_base_python_path()),
        "environment_receipt_id": str(environment_receipt.get("receipt_id") or ""),
        "environment_root": str(EXPECTED_ENV_ROOT),
        "python_version": environment_probe.get("python_version"),
    }


def _manual_gate_output_expiry(value: Any) -> datetime:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 128:
        raise RuntimeError("manual-gate verifier output has no bounded expiry")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("manual-gate verifier output expiry is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("manual-gate verifier output expiry is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _validate_manual_gate_typed_output(
    task_id: str,
    output: Mapping[str, Any],
    *,
    snapshot: Any,
    execution_time: datetime,
    check_freshness: bool,
) -> str:
    profile = _manual_gate_profile(task_id)
    if output.get("schema") != profile["output_schema"] or output.get("accepted") is not True:
        raise RuntimeError("manual-gate verifier did not emit its accepted typed schema")
    expires_at = _manual_gate_output_expiry(output.get("expires_at"))
    if check_freshness and expires_at <= execution_time:
        raise RuntimeError("manual-gate verifier decision was expired at execution")
    if task_id == RELEASE_GATE_TASK_ID:
        fields = (
            "accelerator_commit",
            "accelerator_tree",
            "release_receipt_cid",
            "cutover_receipt_cid",
            "store_generation",
            "schema_checksum",
            "quack_profile",
            "decision_cid",
        )
        effect_id = str(output.get("decision_cid") or "")
    elif task_id == REFINEMENT_GATE_TASK_ID:
        fields = (
            "inventory_snapshot_cid",
            "accepted_plan_root_cid",
            "decision_cid",
            "authorization_cid",
        )
        if (
            output.get("active_plan_root_cid") != snapshot.plan_root_cid
            or output.get("accepted_plan_root_cid") != snapshot.plan_root_cid
            or output.get("repository_tree_id") != snapshot.repository_tree_id
            or _safe_int(output.get("unresolved_gap_count"), -1) != 0
            or (
                output.get("generation_changed") is True
                and not str(output.get("generation_rollover_receipt_cid") or "").strip()
            )
        ):
            raise RuntimeError("inventory-refinement authority binding is stale")
        effect_id = str(output.get("decision_cid") or "")
    elif task_id == PROMOTION_GATE_TASK_ID:
        fields = ("decision_cid", "execution_receipt_cid", "authority_fence_id")
        if (
            output.get("plan_root_cid") != snapshot.plan_root_cid
            or output.get("repository_tree_id") != snapshot.repository_tree_id
        ):
            raise RuntimeError("DuckLake promotion authority binding is stale")
        effect_id = str(output.get("execution_receipt_cid") or "")
    else:
        fields = (
            "activation_receipt_cid",
            "environment_receipt_cid",
            "runtime_generation_id",
        )
        if (
            output.get("plan_root_cid") != snapshot.plan_root_cid
            or output.get("repository_tree_id") != snapshot.repository_tree_id
        ):
            raise RuntimeError("runtime-activation authority binding is stale")
        effect_id = str(output.get("activation_receipt_cid") or "")
    if any(
        not isinstance(output.get(field), str)
        or not str(output.get(field) or "").strip()
        or len(str(output.get(field)).encode("utf-8")) > 4096
        or any(character in str(output.get(field)) for character in ("\0", "\n", "\r"))
        for field in fields
    ):
        raise RuntimeError("manual-gate typed output is missing bounded identity fields")
    return effect_id


def _sealed_memfd(raw: bytes, *, name: str) -> int:
    import fcntl

    if not hasattr(os, "memfd_create"):
        raise RuntimeError("sealed verifier input requires Linux memfd support")
    descriptor = os.memfd_create(
        name,
        getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0),
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RuntimeError("could not populate sealed verifier input")
            view = view[written:]
        os.lseek(descriptor, 0, os.SEEK_SET)
        seals = (
            getattr(fcntl, "F_SEAL_SEAL", 0)
            | getattr(fcntl, "F_SEAL_SHRINK", 0)
            | getattr(fcntl, "F_SEAL_GROW", 0)
            | getattr(fcntl, "F_SEAL_WRITE", 0)
        )
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != seals:
            raise RuntimeError("verifier input memfd did not retain every required seal")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _manual_gate_verifier_argv(
    task_id: str,
    *,
    input_path: str,
    snapshot: Any,
    attestation: Mapping[str, Any],
) -> tuple[str, ...]:
    profile = _manual_gate_profile(task_id)
    argv: list[str] = [str(SEALED_PYTHON_LAUNCHER)]
    if profile["invocation"] == "module":
        argv.extend(("--dqk-manual-module", str(profile["module"])))
    else:
        argv.extend(
            (
                "--dqk-manual-script",
                str(REPO_ROOT / str(attestation["path"])),
            )
        )
    argv.extend(str(item) for item in profile["prefix"])
    argv.extend(("--receipt", input_path))
    if task_id in {
        REFINEMENT_GATE_TASK_ID,
        PROMOTION_GATE_TASK_ID,
        RUNTIME_ACTIVATION_GATE_TASK_ID,
    }:
        argv.extend(("--plan-root", str(snapshot.plan_root_cid)))
        argv.extend(("--repository-tree", str(snapshot.repository_tree_id)))
    argv.extend(str(item) for item in profile["suffix"])
    return tuple(argv)


def _bounded_manual_gate_process_output(
    process: subprocess.Popen[bytes],
    *,
    maximum_bytes: int = 2 * 1024 * 1024,
    timeout_seconds: float = 300.0,
) -> tuple[bytes, bytes]:
    """Drain both verifier pipes incrementally and kill on the first excess."""

    import selectors

    if (
        isinstance(maximum_bytes, bool)
        or not 1 <= maximum_bytes <= 16 * 1024 * 1024
        or not timeout_seconds > 0
        or process.stdout is None
        or process.stderr is None
    ):
        raise RuntimeError("manual-gate verifier output bound is invalid")
    selector = selectors.DefaultSelector()
    streams = {process.stdout.fileno(): "stdout", process.stderr.fileno(): "stderr"}
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    for descriptor, name in streams.items():
        os.set_blocking(descriptor, False)
        selector.register(descriptor, selectors.EVENT_READ, data=name)
    deadline = time.monotonic() + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError("manual-gate verifier exceeded its 300 second bound")
            for key, _mask in selector.select(min(remaining, 0.25)):
                name = str(key.data)
                stream_room = maximum_bytes + 1 - len(buffers[name])
                combined_room = maximum_bytes + 1 - sum(
                    len(value) for value in buffers.values()
                )
                try:
                    chunk = os.read(
                        key.fd,
                        min(64 * 1024, max(1, min(stream_room, combined_room))),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                buffers[name].extend(chunk)
                if len(buffers[name]) > maximum_bytes:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError(
                        f"manual-gate verifier {name} exceeded its byte bound"
                    )
                if sum(len(value) for value in buffers.values()) > maximum_bytes:
                    process.kill()
                    process.wait(timeout=5)
                    raise RuntimeError(
                        "manual-gate verifier combined output exceeded its byte bound"
                    )
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return bytes(buffers["stdout"]), bytes(buffers["stderr"])
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError("manual-gate verifier exceeded its 300 second bound") from exc
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()


def _execute_manual_gate_verifier(
    task_id: str,
    *,
    raw_input: bytes,
    input_capture: Mapping[str, Any],
    snapshot: Any,
    verifier_attestation: Mapping[str, Any],
    interpreter_attestation: Mapping[str, Any],
    decision_preflight: Mapping[str, Any],
) -> dict[str, Any]:
    # Resolve the task-owned adapter before any subprocess can run.  In
    # particular DQK-102/103 stay non-effectful until their transactional
    # execute-once/recovery adapters are materialized by DQK-100/DQK-083.
    authority_adapter = _manual_gate_task_authority_adapter(task_id)
    if _git("rev-parse", "HEAD").lower() != verifier_attestation["repository_commit"]:
        raise RuntimeError("repository HEAD changed after manual-gate preparation")
    current = _manual_gate_verifier_attestation(task_id)
    if current != dict(verifier_attestation):
        raise RuntimeError("manual-gate verifier attestation changed before execution")
    current_interpreter = _manual_gate_interpreter_attestation()
    if current_interpreter != dict(interpreter_attestation):
        raise RuntimeError("manual-gate interpreter attestation changed before execution")
    descriptor = _sealed_memfd(raw_input, name=f"dqk-{task_id.lower()}-receipt")
    input_path = f"/proc/self/fd/{descriptor}"
    argv = _manual_gate_verifier_argv(
        task_id,
        input_path=input_path,
        snapshot=snapshot,
        attestation=verifier_attestation,
    )
    environment = {
        **_sealed_python_environment(),
        "IPFS_DATASETS_DQK_ENV_ROOT": str(EXPECTED_ENV_ROOT),
        "LANG": "C.UTF-8",
    }
    started_at = datetime.now(timezone.utc)
    try:
        process = subprocess.Popen(
            argv,
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(descriptor,),
        )
        process_identity = _process_birth_identity(process.pid)
        stdout, stderr = _bounded_manual_gate_process_output(process)
    finally:
        os.close(descriptor)
    finished_at = datetime.now(timezone.utc)
    if process_identity is None:
        raise RuntimeError("manual-gate verifier process birth could not be identified")
    if process.returncode != 0:
        detail = (stdout + stderr).decode("utf-8", errors="replace").splitlines()[-20:]
        raise RuntimeError("manual-gate verifier rejected the input: " + "\n".join(detail))
    try:
        output_text = stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError("manual-gate verifier output is not UTF-8") from exc
    typed_output = _strict_json_object(output_text, noun="manual-gate verifier output")
    effect_receipt_id = _validate_manual_gate_typed_output(
        task_id,
        typed_output,
        snapshot=snapshot,
        execution_time=finished_at,
        check_freshness=True,
    )
    if _manual_gate_verifier_attestation(task_id) != dict(verifier_attestation):
        raise RuntimeError("manual-gate verifier changed during execution")
    decision_verification = authority_adapter.verify_execution(
        task_id=task_id,
        raw_input=raw_input,
        typed_output=typed_output,
        snapshot=snapshot,
        execution_time=finished_at,
        verifier_attestation=dict(verifier_attestation),
        decision_preflight=dict(decision_preflight),
        historical=False,
    )
    if not isinstance(decision_verification, Mapping):
        raise RuntimeError("manual-gate signed-decision adapter returned no typed proof")
    blob_store = _manual_gate_blob_store()
    stdout_blob = blob_store.put("stdout", stdout)
    stderr_blob = blob_store.put("stderr", stderr)
    receipt: dict[str, Any] = {
        "schema": MANUAL_GATE_EXECUTION_SCHEMA,
        "gate_task_id": task_id,
        "owner_task_id": MANUAL_GATE_OWNER_TASK_IDS[task_id],
        "authority_effect_id": MANUAL_GATE_AUTHORITY_EFFECT_IDS[task_id],
        "input_capture": dict(input_capture),
        "decision_preflight": dict(decision_preflight),
        "decision_verification": dict(decision_verification),
        "verifier": dict(verifier_attestation),
        "interpreter": dict(interpreter_attestation),
        "argv": list(argv),
        "environment": environment,
        "stdin_sha256": f"sha256:{hashlib.sha256(b'').hexdigest()}",
        "process": {
            **dict(process_identity),
            "returncode": process.returncode,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "stdout_sha256": f"sha256:{hashlib.sha256(stdout).hexdigest()}",
            "stderr_sha256": f"sha256:{hashlib.sha256(stderr).hexdigest()}",
            "stdout_blob": stdout_blob,
            "stderr_blob": stderr_blob,
        },
        "typed_output": typed_output,
        "effect_receipt_id": effect_receipt_id,
        "freshness_checked_at": finished_at.isoformat(),
    }
    execution_blob_body = _canonical_json(receipt).encode("utf-8")
    receipt["execution_blob"] = blob_store.put("execution", execution_blob_body)
    receipt["execution_id"] = _manual_gate_receipt_id(
        "manual-gate-verifier-execution", receipt
    )
    return receipt


def _manual_gate_lifecycle_id(
    task_id: str,
    *,
    task_cid: str,
    snapshot: Any,
    input_capture: Mapping[str, Any],
) -> str:
    return _manual_gate_receipt_id(
        "manual-gate-lifecycle",
        {
            "program_id": PROGRAM_ID,
            "gate_task_id": task_id,
            "gate_task_cid": task_cid,
            "owner_task_id": MANUAL_GATE_OWNER_TASK_IDS[task_id],
            "plan_root_cid": snapshot.plan_root_cid,
            "repository_tree_id": snapshot.repository_tree_id,
            "input_capture": dict(input_capture),
        },
    )


def _manual_gate_journal_path(lifecycle_id: str) -> Path:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", lifecycle_id) is None:
        raise RuntimeError("manual-gate lifecycle identity is invalid")
    return MANUAL_GATE_LIFECYCLE_ROOT / f"{lifecycle_id.split(':', 1)[1]}.json"


@contextmanager
def _manual_gate_lock_context() -> Iterable[None]:
    import fcntl
    import stat

    MANUAL_GATE_LIFECYCLE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_metadata = MANUAL_GATE_LIFECYCLE_ROOT.lstat()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or MANUAL_GATE_LIFECYCLE_ROOT.is_symlink()
        or root_metadata.st_uid != os.geteuid()
        or root_metadata.st_mode & 0o077
    ):
        raise RuntimeError("manual-gate lifecycle root is not owner-controlled")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(MANUAL_GATE_LIFECYCLE_LOCK, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise RuntimeError("manual-gate lifecycle lock is not owner-controlled")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _seal_manual_gate_journal(journal: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(journal)
    sealed["journal_cid"] = _manual_gate_receipt_id("manual-gate-journal", sealed)
    return sealed


def _write_manual_gate_journal(path: Path, journal: Mapping[str, Any]) -> dict[str, Any]:
    import stat

    if path != _manual_gate_journal_path(str(journal.get("lifecycle_id") or "")):
        raise RuntimeError("manual-gate journal path is not content-bound")
    if path.is_symlink():
        raise RuntimeError("manual-gate journal cannot replace a symlink")
    if path.exists():
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise RuntimeError("manual-gate journal is not owner-controlled")
    sealed = _seal_manual_gate_journal(journal)
    _atomic_write_text(path, json.dumps(sealed, indent=2, sort_keys=True) + "\n")
    return sealed


def _read_manual_gate_journal(path: Path) -> dict[str, Any]:
    raw = _read_nofollow_bounded_file(path)
    try:
        payload = _strict_json_object(
            raw.decode("utf-8", errors="strict"), noun="manual-gate journal"
        )
    except UnicodeDecodeError as exc:
        raise RuntimeError("manual-gate journal is not UTF-8") from exc
    if (
        payload.get("schema") != MANUAL_GATE_JOURNAL_SCHEMA
        or payload.get("phase") not in MANUAL_GATE_PHASES
        or path != _manual_gate_journal_path(str(payload.get("lifecycle_id") or ""))
        or payload.get("journal_cid")
        != _manual_gate_receipt_id("manual-gate-journal", payload)
    ):
        raise RuntimeError("manual-gate journal identity or schema is invalid")
    return payload


def _manual_gate_lifecycle_inspection() -> dict[str, Any]:
    """Boundedly surface every incomplete or malformed gate lifecycle."""

    import stat

    root = MANUAL_GATE_LIFECYCLE_ROOT
    if not root.exists():
        return {"ok": True, "incomplete": [], "error": ""}
    try:
        metadata = root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or root.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise RuntimeError("manual-gate lifecycle root is not owner-controlled")
        paths: list[Path] = []
        for entry in os.scandir(root):
            if entry.name == MANUAL_GATE_LIFECYCLE_LOCK.name:
                lock_metadata = entry.stat(follow_symlinks=False)
                if (
                    entry.is_symlink()
                    or not stat.S_ISREG(lock_metadata.st_mode)
                    or lock_metadata.st_uid != os.geteuid()
                    or lock_metadata.st_mode & 0o077
                ):
                    raise RuntimeError("manual-gate lifecycle lock is not owner-controlled")
                continue
            if entry.name == "blobs":
                blob_metadata = entry.stat(follow_symlinks=False)
                if (
                    entry.is_symlink()
                    or not stat.S_ISDIR(blob_metadata.st_mode)
                    or blob_metadata.st_uid != os.geteuid()
                    or blob_metadata.st_mode & 0o077
                ):
                    raise RuntimeError("manual-gate blob root is not owner-controlled")
                blob_entries = list(os.scandir(entry.path))
                if len(blob_entries) > 512:
                    raise RuntimeError("manual-gate blob population exceeds 512")
                for blob_entry in blob_entries:
                    item = blob_entry.stat(follow_symlinks=False)
                    if (
                        blob_entry.is_symlink()
                        or not stat.S_ISREG(item.st_mode)
                        or item.st_uid != os.geteuid()
                        or item.st_mode & 0o077
                        or (
                            re.fullmatch(r"[0-9a-f]{64}\.blob", blob_entry.name)
                            is None
                            and re.fullmatch(
                                r"\.[0-9a-f]{64}\.blob\.[0-9]+\.[0-9a-f]{16}\.tmp",
                                blob_entry.name,
                            )
                            is None
                        )
                        or not 0 <= item.st_size <= 2 * 1024 * 1024
                    ):
                        raise RuntimeError("manual-gate blob root has an invalid entry")
                continue
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise RuntimeError("manual-gate lifecycle root has an unsupported entry")
            if re.fullmatch(r"[0-9a-f]{64}\.json", entry.name) is None:
                raise RuntimeError("manual-gate lifecycle root has an unrecognized file")
            paths.append(Path(entry.path))
        if len(paths) > 64:
            raise RuntimeError("manual-gate lifecycle journal population exceeds 64")
        incomplete: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in sorted(paths):
            journal = _read_manual_gate_journal(path)
            lifecycle_id = str(journal["lifecycle_id"])
            if lifecycle_id in seen:
                raise RuntimeError("manual-gate lifecycle identity is duplicated")
            seen.add(lifecycle_id)
            if journal["phase"] != "RELEASED":
                incomplete.append(
                    {
                        "lifecycle_id": lifecycle_id,
                        "gate_task_id": str(journal.get("gate_task_id") or ""),
                        "phase": str(journal["phase"]),
                        "journal_path": str(path),
                    }
                )
        return {"ok": not incomplete, "incomplete": incomplete, "error": ""}
    except Exception as exc:
        return {
            "ok": False,
            "incomplete": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _manual_gate_crash_boundary(_phase: str) -> None:
    """Test hook for process-death replay at every lifecycle boundary."""


def _manual_gate_snapshot(source: Any) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    snapshot, tables, _counts = _consistent_rows(source, ("tasks", "task_events"))
    tasks = {
        str(row.get("task_alias") or ""): row for row in tables["tasks"]
    }
    if len(tasks) != len(tables["tasks"]):
        raise RuntimeError("manual-gate task projection contains duplicate aliases")
    return snapshot, tasks, {"task_events": tables["task_events"]}


def _manual_gate_checkout_module() -> Any:
    return _accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.checkout_lock",
        "ipfs_accelerate_py.agent_supervisor.checkout_lock",
    )


def _acquire_or_adopt_manual_gate_effect_leases(
    journal: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    if journal.get("gate_task_id") != RELEASE_GATE_TASK_ID:
        return ()
    existing = journal.get("checkout_leases") or ()
    if not isinstance(existing, (list, tuple)) or not all(
        isinstance(item, Mapping) for item in existing
    ):
        raise RuntimeError("manual-gate checkout lease journal is malformed")
    return manual_gate_authority.acquire_or_adopt_checkout_leases(
        {"parent": REPO_ROOT, "accelerator": ACCELERATE_ROOT},
        operation_id=str(journal["lifecycle_id"]),
        checkout_module=_manual_gate_checkout_module(),
        expected_records=tuple(existing),
    )


def _assert_manual_gate_effect_leases(journal: Mapping[str, Any]) -> None:
    if journal.get("gate_task_id") != RELEASE_GATE_TASK_ID:
        return
    records = journal.get("checkout_leases")
    if not isinstance(records, list):
        raise RuntimeError("DQK-056 has no persistent checkout lease set")
    relaunch = journal.get("relaunch")
    standalone = journal.get("checkout_custodian")
    expected_custodian = next(
        (
            item
            for item in (relaunch, standalone)
            if isinstance(item, Mapping)
            and _safe_int(item.get("pid")) > 0
            and _identity_is_live(item)
        ),
        None,
    )
    manual_gate_authority.assert_checkout_leases(
        records,
        checkout_module=_manual_gate_checkout_module(),
        expected_custodian=expected_custodian,
    )


def _bind_manual_gate_relaunch_custodian(
    journal: Mapping[str, Any], relaunch: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    if journal.get("gate_task_id") != RELEASE_GATE_TASK_ID:
        return ()
    records = journal.get("checkout_leases")
    if not isinstance(records, list):
        raise RuntimeError("DQK-056 has no persistent checkout lease set")
    if _safe_int(relaunch.get("pid")) <= 0:
        return tuple(dict(item) for item in records)
    return manual_gate_authority.bind_checkout_leases_to_custodian(
        records,
        custodian=relaunch,
        owner_script=manual_gate_authority.compatibility_owner_script(relaunch),
        checkout_module=_manual_gate_checkout_module(),
    )


def _prepare_manual_gate_effect(
    task_id: str,
    *,
    journal: Mapping[str, Any],
    execution: Mapping[str, Any],
    source: Any,
    snapshot: Any,
) -> dict[str, Any]:
    del source
    output = execution.get("typed_output")
    if not isinstance(output, Mapping):
        raise RuntimeError("manual-gate effect has no typed verifier output")
    if task_id == RELEASE_GATE_TASK_ID:
        checkout_module = _manual_gate_checkout_module()
        _assert_manual_gate_effect_leases(journal)
        return manual_gate_authority.prepare_gitlink_pin(
            parent=REPO_ROOT,
            accelerator=ACCELERATE_ROOT,
            target_branch=TARGET_BRANCH,
            desired_commit=str(output.get("accelerator_commit") or "").lower(),
            desired_tree=str(output.get("accelerator_tree") or "").lower(),
            operation_id=str(journal["lifecycle_id"]),
            checkout_leases=tuple(journal["checkout_leases"]),
            checkout_module=checkout_module,
            protected_paths=(
                Path(__file__).resolve().relative_to(REPO_ROOT).as_posix(),
                MANUAL_GATE_AUTHORITY_MODULE.relative_to(REPO_ROOT).as_posix(),
                BOOTSTRAP_REQUIREMENTS.relative_to(REPO_ROOT).as_posix(),
            ),
        )
    if task_id == REFINEMENT_GATE_TASK_ID:
        intent: dict[str, Any] = {
            "schema": "ipfs_datasets_py/duckdb-quack-manual-gate-rollover-intent@2",
            "operation_id": journal["lifecycle_id"],
            "execution_id": execution["execution_id"],
            "plan_root_cid": snapshot.plan_root_cid,
            "repository_tree_id": snapshot.repository_tree_id,
            "generation_changed": output.get("generation_changed"),
            "generation_rollover_receipt_cid": str(
                output.get("generation_rollover_receipt_cid") or ""
            ),
        }
        intent["intent_id"] = _manual_gate_receipt_id(
            "manual-gate-rollover-intent", intent
        )
        return intent
    raise RuntimeError(f"manual_gate_effect_adapter_not_materialized:{task_id}")


def _apply_manual_gate_effect(
    task_id: str,
    *,
    journal: Mapping[str, Any],
    execution: Mapping[str, Any],
    source: Any,
    snapshot: Any,
) -> dict[str, Any]:
    intent = journal.get("effect_intent")
    output = execution.get("typed_output")
    if not isinstance(intent, Mapping) or not isinstance(output, Mapping):
        raise RuntimeError("manual-gate effect intent or output is missing")
    if task_id == RELEASE_GATE_TASK_ID:
        checkout_module = _manual_gate_checkout_module()
        _assert_manual_gate_effect_leases(journal)
        return manual_gate_authority.apply_or_rederive_gitlink_pin(
            parent=REPO_ROOT,
            intent=intent,
        )
    if task_id == REFINEMENT_GATE_TASK_ID:
        projection = source.read_consistent_projection(("materialization_receipts",))
        if (
            projection.snapshot.plan_root_cid != snapshot.plan_root_cid
            or projection.snapshot.repository_tree_id != snapshot.repository_tree_id
        ):
            raise RuntimeError("DQK-081 source generation changed after verification")
        identity = _repository_task_source_identity(source, projection.snapshot)
        writer = _repository_task_source_writer(source)
        receipt = manual_gate_authority.rollover_binding(
            output=output,
            snapshot=projection.snapshot,
            source_identity=identity,
            writer=writer,
            materialization_receipts=tuple(
                projection.tables.get("materialization_receipts") or ()
            ),
            content_identity=_repository_content_identity,
        )
        if receipt.get("generation_changed") != intent.get("generation_changed"):
            raise RuntimeError("DQK-081 rollover effect differs from its intent")
        return receipt
    raise RuntimeError(f"manual_gate_effect_adapter_not_materialized:{task_id}")


def _validate_manual_gate_effect_receipt(
    task_id: str,
    *,
    effect_receipt: Mapping[str, Any],
    effect_intent: Mapping[str, Any],
    snapshot: Any,
    materialization_receipts: Sequence[Mapping[str, Any]] = (),
    task_source_identity_id: str = "",
    current_writer: tuple[str, int] | None = None,
) -> None:
    if task_id == RELEASE_GATE_TASK_ID:
        manual_gate_authority.validate_gitlink_pin_receipt(
            parent=REPO_ROOT,
            accelerator=ACCELERATE_ROOT,
            receipt=effect_receipt,
            intent=effect_intent,
        )
        return
    if task_id == REFINEMENT_GATE_TASK_ID:
        expected_intent_keys = {
            "schema",
            "operation_id",
            "execution_id",
            "plan_root_cid",
            "repository_tree_id",
            "generation_changed",
            "generation_rollover_receipt_cid",
            "intent_id",
        }
        if (
            set(effect_intent) != expected_intent_keys
            or effect_intent.get("schema")
            != "ipfs_datasets_py/duckdb-quack-manual-gate-rollover-intent@2"
            or not str(effect_intent.get("operation_id") or "")
            or not str(effect_intent.get("execution_id") or "")
            or effect_intent.get("plan_root_cid") != snapshot.plan_root_cid
            or effect_intent.get("repository_tree_id")
            != snapshot.repository_tree_id
            or effect_intent.get("generation_changed")
            is not effect_receipt.get("generation_changed")
            or effect_intent.get("generation_rollover_receipt_cid")
            != str(
                (effect_receipt.get("materialization_receipt") or {}).get(
                    "receipt_cid"
                )
                or ""
            )
            or effect_intent.get("intent_id")
            != _manual_gate_receipt_id(
                "manual-gate-rollover-intent",
                {
                    key: value
                    for key, value in effect_intent.items()
                    if key != "intent_id"
                },
            )
        ):
            raise RuntimeError("DQK-081 rollover intent is stale or malformed")
        selected = effect_receipt.get("materialization_receipt")
        source_identity = effect_receipt.get("task_source_identity")
        writer = effect_receipt.get("writer")
        TaskSourceIdentity, _Evidence, _Daemon = _repository_authority_types()
        expected_identity_keys = {
            "schema",
            "protocol_schema",
            "source_kind",
            "locator",
            "source_id",
            "root_id",
            "source_schema",
            "schema_version",
            "repository_root_id",
            "identity_id",
        }
        if not isinstance(source_identity, Mapping) or set(source_identity) != expected_identity_keys:
            raise RuntimeError("DQK-081 task-source identity shape is invalid")
        rederived_identity = TaskSourceIdentity.from_dict(source_identity).to_dict()
        effect_projection_cid = str(effect_receipt.get("projection_cid") or "")
        if (
            rederived_identity != dict(source_identity)
            or source_identity.get("source_kind") != "duckdb"
            or not effect_projection_cid
            or len(effect_projection_cid.encode("utf-8")) > 512
            or source_identity.get("source_id") != effect_projection_cid
            or source_identity.get("root_id") != snapshot.plan_root_cid
            or source_identity.get("repository_root_id")
            != snapshot.repository_tree_id
            or source_identity.get("source_schema") != snapshot.source_schema
            or source_identity.get("schema_version") != snapshot.schema_version
            or not task_source_identity_id
            or source_identity.get("identity_id") != task_source_identity_id
        ):
            raise RuntimeError("DQK-081 task-source identity is stale or detached")
        if (
            not isinstance(writer, Mapping)
            or set(writer) != {"writer_id", "fencing_token"}
            or not isinstance(writer.get("writer_id"), str)
            or not writer.get("writer_id")
            or isinstance(writer.get("fencing_token"), bool)
            or not isinstance(writer.get("fencing_token"), int)
            or writer.get("fencing_token", 0) < 1
        ):
            raise RuntimeError("DQK-081 changed rollover lacks a writer fence")
        if (
            current_writer is None
            or writer.get("writer_id") != current_writer[0]
            or int(writer["fencing_token"]) > current_writer[1]
        ):
            raise RuntimeError("DQK-081 writer fence is not in current authority")
        if (
            effect_receipt.get("schema")
            != manual_gate_authority.ROLLOVER_BINDING_SCHEMA
            or effect_receipt.get("plan_root_cid") != snapshot.plan_root_cid
            or effect_receipt.get("repository_tree_id")
            != snapshot.repository_tree_id
            or effect_receipt.get("generation_changed")
            is not effect_intent.get("generation_changed")
            or effect_receipt.get("binding_id")
            != manual_gate_authority.content_id(
                "manual-gate-rollover-binding",
                {
                    key: value
                    for key, value in effect_receipt.items()
                    if key != "binding_id"
                },
            )
        ):
            raise RuntimeError("DQK-081 rollover binding is stale or invalid")
        if effect_receipt.get("generation_changed") is True:
            if not isinstance(selected, Mapping):
                raise RuntimeError("DQK-081 changed generation lacks materialization authority")
            stored = {
                key: value for key, value in selected.items() if key != "body"
            }
            body = selected.get("body")
            if (
                stored not in [dict(item) for item in materialization_receipts]
                or not isinstance(body, Mapping)
                or _strict_json_object(
                    str(stored.get("body_json") or ""),
                    noun="DQK-081 historical materialization receipt",
                )
                != dict(body)
                or stored.get("receipt_cid")
                != _repository_content_identity(body)
                or body.get("projection_cid") != effect_projection_cid
            ):
                raise RuntimeError("DQK-081 rollover binding is not in DuckDB authority")
        elif selected is not None:
            raise RuntimeError("DQK-081 unchanged generation has rollover evidence")
        return
    raise RuntimeError(f"manual_gate_effect_adapter_not_materialized:{task_id}")


def _manual_gate_cas_receipt(
    journal: Mapping[str, Any],
    execution: Mapping[str, Any],
    effect_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": MANUAL_GATE_CAS_RECEIPT_SCHEMA,
        "lifecycle_id": journal["lifecycle_id"],
        "gate_task_id": journal["gate_task_id"],
        "gate_task_cid": journal["gate_task_cid"],
        "owner_task_id": journal["owner_task_id"],
        "authority_effect_id": journal["authority_effect_id"],
        "input_capture": journal["input_capture"],
        "execution": dict(execution),
        "effect_intent": dict(journal["effect_intent"]),
        "effect_receipt": dict(effect_receipt),
        "plan_root_cid": journal["plan_root_cid"],
        "repository_tree_id": journal["repository_tree_id"],
        "task_source_identity_id": journal["task_source_identity_id"],
        "expected_task_revision": journal["expected_task_revision"],
        "prepared_journal_cid": journal["prepared_journal_cid"],
        "runtime_drain": dict(journal["runtime_drain"]),
        "runtime_drained": dict(journal["runtime_drained"]),
        "completed_at": str(execution["process"]["finished_at"]),
    }
    receipt["receipt_id"] = _manual_gate_receipt_id("manual-gate-cas", receipt)
    return receipt


def _validate_manual_gate_execution_receipt(
    task_id: str,
    execution: Mapping[str, Any],
    *,
    snapshot: Any,
    input_capture: Mapping[str, Any],
) -> None:
    _strict_json_object(
        _canonical_json(dict(execution)), noun="manual-gate execution receipt"
    )
    expected_keys = {
        "schema",
        "gate_task_id",
        "owner_task_id",
        "authority_effect_id",
        "input_capture",
        "decision_preflight",
        "decision_verification",
        "verifier",
        "interpreter",
        "argv",
        "environment",
        "stdin_sha256",
        "process",
        "typed_output",
        "effect_receipt_id",
        "freshness_checked_at",
        "execution_blob",
        "execution_id",
    }
    if set(execution) != expected_keys:
        raise RuntimeError("manual-gate execution receipt shape is unsupported")
    if (
        execution.get("schema") != MANUAL_GATE_EXECUTION_SCHEMA
        or execution.get("gate_task_id") != task_id
        or execution.get("owner_task_id") != MANUAL_GATE_OWNER_TASK_IDS[task_id]
        or execution.get("authority_effect_id")
        != MANUAL_GATE_AUTHORITY_EFFECT_IDS[task_id]
        or execution.get("input_capture") != dict(input_capture)
        or execution.get("execution_id")
        != _manual_gate_receipt_id("manual-gate-verifier-execution", execution)
        or execution.get("stdin_sha256")
        != f"sha256:{hashlib.sha256(b'').hexdigest()}"
    ):
        raise RuntimeError("manual-gate execution receipt identity is invalid")
    if set(input_capture) != {
        "schema",
        "byte_length",
        "sha256",
        "canonical_json_sha256",
        "blob",
    } or (
        input_capture.get("schema")
        != "ipfs_datasets_py/manual-gate-immutable-input@2"
        or not 1 <= _safe_int(input_capture.get("byte_length"), 0) <= 2 * 1024 * 1024
        or any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", str(input_capture.get(key) or ""))
            is None
            for key in ("sha256", "canonical_json_sha256")
        )
    ):
        raise RuntimeError("manual-gate immutable input capture is invalid")
    raw_input = _manual_gate_read_bound_input(input_capture)
    execution_blob = execution.get("execution_blob")
    if not isinstance(execution_blob, Mapping):
        raise RuntimeError("manual-gate execution has no immutable body blob")
    persisted_execution = _manual_gate_blob_store().read(
        execution_blob, expected_kind="execution"
    )
    expected_execution_body = {
        key: value
        for key, value in execution.items()
        if key not in {"execution_blob", "execution_id"}
    }
    if persisted_execution != _canonical_json(expected_execution_body).encode("utf-8"):
        raise RuntimeError("manual-gate execution blob is detached from its receipt")
    verifier = execution.get("verifier")
    interpreter = execution.get("interpreter")
    process = execution.get("process")
    argv = execution.get("argv")
    environment = execution.get("environment")
    if not all(
        isinstance(value, Mapping)
        for value in (verifier, interpreter, process, environment)
    ) or not isinstance(argv, list):
        raise RuntimeError("manual-gate execution bindings are not typed")
    decision_preflight = execution.get("decision_preflight")
    decision_verification = execution.get("decision_verification")
    if not isinstance(decision_preflight, Mapping) or not isinstance(
        decision_verification, Mapping
    ):
        raise RuntimeError("manual-gate signed-decision proof is missing")
    if set(verifier) != {
        "repository_commit",
        "repository_tree",
        "path",
        "git_blob_sha256",
        "byte_length",
        "invocation",
        "module",
    } or set(interpreter) != {
        "launcher_path",
        "launcher_sha256",
        "base_python_path",
        "base_python_sha256",
        "environment_receipt_id",
        "environment_root",
        "python_version",
    }:
        raise RuntimeError("manual-gate verifier/interpreter attestation shape is unsupported")
    profile = _manual_gate_profile(task_id)
    commit = str(verifier.get("repository_commit") or "")
    relative_path = str(verifier.get("path") or "")
    if (
        relative_path != profile["verifier_path"]
        or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None
        or _git("rev-parse", f"{commit}^{{tree}}").lower()
        != str(verifier.get("repository_tree") or "").lower()
    ):
        raise RuntimeError("manual-gate verifier Git identity is invalid")
    blob = _git_blob(commit, relative_path, maximum_bytes=2 * 1024 * 1024)
    if (
        verifier.get("git_blob_sha256")
        != f"sha256:{hashlib.sha256(blob).hexdigest()}"
        or _safe_int(verifier.get("byte_length"), -1) != len(blob)
    ):
        raise RuntimeError("manual-gate verifier Git blob digest is invalid")
    for key in ("launcher_sha256", "base_python_sha256"):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", str(interpreter.get(key) or "")) is None:
            raise RuntimeError("manual-gate interpreter digest is invalid")
    if environment != {
        **_sealed_python_environment(),
        "IPFS_DATASETS_DQK_ENV_ROOT": str(EXPECTED_ENV_ROOT),
        "LANG": "C.UTF-8",
    }:
        raise RuntimeError("manual-gate verifier environment is not the sealed allowlist")
    if (
        not argv
        or any(
            not isinstance(item, str)
            or not item
            or len(item.encode("utf-8")) > 8192
            or "\0" in item
            for item in argv
        )
        or argv.count("--receipt") != 1
    ):
        raise RuntimeError("manual-gate verifier argv is not a bounded exact vector")
    input_path = _option_value(argv, "--receipt")
    if re.fullmatch(r"/proc/self/fd/[0-9]+", input_path) is None:
        raise RuntimeError("manual-gate verifier did not consume its sealed input fd")
    expected_argv = _manual_gate_verifier_argv(
        task_id,
        input_path=input_path,
        snapshot=snapshot,
        attestation=verifier,
    )
    if tuple(argv) != expected_argv:
        raise RuntimeError("manual-gate verifier argv differs from its canonical profile")
    observed_argv = process.get("argv")
    if not isinstance(observed_argv, (list, tuple)) or any(
        not isinstance(item, str) or not item or "\0" in item
        for item in observed_argv
    ):
        raise RuntimeError("manual-gate verifier process argv is invalid")
    observed_cmdline = b"\0".join(
        item.encode("utf-8") for item in observed_argv
    ) + b"\0"
    if (
        _safe_int(process.get("pid"), 0) < 1
        or _safe_int(process.get("start_ticks"), 0) < 1
        or _safe_int(process.get("returncode"), -1) != 0
        or process.get("cmdline_sha256")
        != f"sha256:{hashlib.sha256(observed_cmdline).hexdigest()}"
        or argv[0] != str(interpreter.get("launcher_path") or "")
    ):
        raise RuntimeError("manual-gate verifier process binding is invalid")
    for key in ("cmdline_sha256", "stdout_sha256", "stderr_sha256"):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", str(process.get(key) or "")) is None:
            raise RuntimeError("manual-gate process digest is invalid")
    stdout_blob = process.get("stdout_blob")
    stderr_blob = process.get("stderr_blob")
    if not isinstance(stdout_blob, Mapping) or not isinstance(stderr_blob, Mapping):
        raise RuntimeError("manual-gate process output blobs are missing")
    stdout = _manual_gate_blob_store().read(stdout_blob, expected_kind="stdout")
    stderr = _manual_gate_blob_store().read(stderr_blob, expected_kind="stderr")
    if (
        process.get("stdout_sha256")
        != f"sha256:{hashlib.sha256(stdout).hexdigest()}"
        or process.get("stderr_sha256")
        != f"sha256:{hashlib.sha256(stderr).hexdigest()}"
    ):
        raise RuntimeError("manual-gate process output digest is detached from bytes")
    try:
        started_at = datetime.fromisoformat(
            str(process["started_at"]).replace("Z", "+00:00")
        )
        finished_at = datetime.fromisoformat(
            str(process["finished_at"]).replace("Z", "+00:00")
        )
        checked_at = datetime.fromisoformat(
            str(execution["freshness_checked_at"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("manual-gate process timestamps are invalid") from exc
    if (
        any(value.tzinfo is None or value.utcoffset() is None for value in (started_at, finished_at, checked_at))
        or not started_at <= finished_at == checked_at
    ):
        raise RuntimeError("manual-gate execution timeline is invalid")
    typed_output = execution.get("typed_output")
    if not isinstance(typed_output, Mapping):
        raise RuntimeError("manual-gate typed output is missing")
    try:
        persisted_output = _strict_json_object(
            stdout.decode("utf-8", errors="strict"),
            noun="manual-gate persisted verifier output",
        )
    except UnicodeDecodeError as exc:
        raise RuntimeError("manual-gate persisted stdout is not UTF-8") from exc
    if persisted_output != dict(typed_output):
        raise RuntimeError("manual-gate typed output differs from exact stdout")
    effect_receipt_id = _validate_manual_gate_typed_output(
        task_id,
        typed_output,
        snapshot=snapshot,
        execution_time=checked_at,
        check_freshness=True,
    )
    if execution.get("effect_receipt_id") != effect_receipt_id:
        raise RuntimeError("manual-gate authority effect receipt is detached")
    independently_verified = _manual_gate_task_authority_adapter(
        task_id
    ).verify_execution(
        task_id=task_id,
        raw_input=raw_input,
        typed_output=dict(typed_output),
        snapshot=snapshot,
        execution_time=checked_at,
        verifier_attestation=dict(verifier),
        decision_preflight=dict(decision_preflight),
        historical=True,
    )
    if not isinstance(independently_verified, Mapping) or dict(
        independently_verified
    ) != dict(decision_verification):
        raise RuntimeError(
            "manual-gate signed decision failed independent historical verification"
        )


def _validate_manual_gate_cas_receipt(
    receipt: Mapping[str, Any],
    *,
    task_row: Mapping[str, Any],
    snapshot: Any,
    require_released: bool,
    materialization_receipts: Sequence[Mapping[str, Any]] = (),
    current_writer: tuple[str, int] | None = None,
) -> tuple[bool, str]:
    task_id = str(task_row.get("task_alias") or "")
    expected_keys = {
        "schema",
        "lifecycle_id",
        "gate_task_id",
        "gate_task_cid",
        "owner_task_id",
        "authority_effect_id",
        "input_capture",
        "execution",
        "effect_intent",
        "effect_receipt",
        "plan_root_cid",
        "repository_tree_id",
        "task_source_identity_id",
        "expected_task_revision",
        "prepared_journal_cid",
        "runtime_drain",
        "runtime_drained",
        "completed_at",
        "receipt_id",
    }
    try:
        if set(receipt) != expected_keys:
            raise RuntimeError("manual-gate CAS receipt shape is unsupported")
        input_capture = receipt.get("input_capture")
        execution = receipt.get("execution")
        effect_intent = receipt.get("effect_intent")
        effect_receipt = receipt.get("effect_receipt")
        runtime_drain = receipt.get("runtime_drain")
        runtime_drained = receipt.get("runtime_drained")
        if not all(
            isinstance(value, Mapping)
            for value in (
                input_capture,
                execution,
                effect_intent,
                effect_receipt,
                runtime_drain,
                runtime_drained,
            )
        ):
            raise RuntimeError("manual-gate receipt lacks typed input/execution/effect")
        if (
            receipt.get("schema") != MANUAL_GATE_CAS_RECEIPT_SCHEMA
            or receipt.get("gate_task_id") != task_id
            or receipt.get("gate_task_cid") != str(task_row.get("task_cid") or "")
            or receipt.get("owner_task_id") != MANUAL_GATE_OWNER_TASK_IDS[task_id]
            or receipt.get("authority_effect_id")
            != MANUAL_GATE_AUTHORITY_EFFECT_IDS[task_id]
            or receipt.get("plan_root_cid") != snapshot.plan_root_cid
            or receipt.get("repository_tree_id") != snapshot.repository_tree_id
            or receipt.get("receipt_id")
            != _manual_gate_receipt_id("manual-gate-cas", receipt)
            or receipt.get("lifecycle_id")
            != _manual_gate_lifecycle_id(
                task_id,
                task_cid=str(task_row.get("task_cid") or ""),
                snapshot=snapshot,
                input_capture=input_capture,
            )
            or str(receipt.get("task_source_identity_id") or "").strip() == ""
            or _safe_int(receipt.get("expected_task_revision"), 0) < 1
            or str(task_row.get("status") or "") != "completed"
            or _safe_int(task_row.get("revision"), 0)
            != _safe_int(receipt.get("expected_task_revision"), 0) + 1
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(receipt.get("prepared_journal_cid") or "")
            )
            is None
        ):
            raise RuntimeError("manual-gate CAS receipt identity is stale or foreign")
        _validate_manual_gate_execution_receipt(
            task_id,
            execution,
            snapshot=snapshot,
            input_capture=input_capture,
        )
        _validate_manual_gate_runtime_drained(
            str(receipt["lifecycle_id"]), runtime_drain, runtime_drained
        )
        _validate_manual_gate_effect_receipt(
            task_id,
            effect_receipt=effect_receipt,
            effect_intent=effect_intent,
            snapshot=snapshot,
            materialization_receipts=materialization_receipts,
            task_source_identity_id=str(
                receipt.get("task_source_identity_id") or ""
            ),
            current_writer=current_writer,
        )
        if effect_intent.get("operation_id") != receipt.get("lifecycle_id"):
            raise RuntimeError("manual-gate effect intent belongs to another lifecycle")
        if (
            task_id == REFINEMENT_GATE_TASK_ID
            and effect_intent.get("execution_id") != execution.get("execution_id")
        ):
            raise RuntimeError("DQK-081 effect intent belongs to another execution")
        completed_at = datetime.fromisoformat(
            str(receipt["completed_at"]).replace("Z", "+00:00")
        )
        execution_finished = datetime.fromisoformat(
            str(execution["process"]["finished_at"]).replace("Z", "+00:00")
        )
        if completed_at != execution_finished:
            raise RuntimeError("manual-gate CAS completion is detached from execution")
        if require_released:
            journal = _read_manual_gate_journal(
                _manual_gate_journal_path(str(receipt["lifecycle_id"]))
            )
            release = journal.get("release_receipt")
            effect_id = str(
                effect_receipt.get("receipt_id")
                or effect_receipt.get("binding_id")
                or ""
            )
            if (
                journal.get("phase") != "RELEASED"
                or journal.get("cas_receipt_id") != receipt["receipt_id"]
                or journal.get("cas_receipt") != dict(receipt)
                or journal.get("effect_intent") != dict(effect_intent)
                or journal.get("effect_receipt") != dict(effect_receipt)
                or not isinstance(release, Mapping)
                or set(release)
                != {
                    "schema",
                    "lifecycle_id",
                    "gate_task_id",
                    "cas_receipt_id",
                    "execution_id",
                    "effect_receipt_id",
                    "checkout_release_set_id",
                    "completed_task_revision",
                    "relaunch",
                    "released_at",
                    "release_id",
                }
                or release.get("schema") != MANUAL_GATE_RELEASE_RECEIPT_SCHEMA
                or release.get("gate_task_id") != task_id
                or release.get("lifecycle_id") != receipt["lifecycle_id"]
                or release.get("cas_receipt_id") != receipt["receipt_id"]
                or release.get("execution_id") != execution["execution_id"]
                or release.get("effect_receipt_id") != effect_id
                or release.get("checkout_release_set_id")
                != _validate_manual_gate_checkout_release(journal)
                or _safe_int(release.get("completed_task_revision"), 0)
                != _safe_int(task_row.get("revision"), 0)
                or release.get("release_id")
                != _manual_gate_receipt_id("manual-gate-release", release)
            ):
                raise RuntimeError("manual-gate lifecycle has not reached RELEASED")
        return True, f"authenticated_execution={execution['execution_id']}"
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _manual_gate_hold_projection_from_tables(
    snapshot: Any,
    tasks: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    materialization_receipts: Sequence[Mapping[str, Any]] = (),
    current_writer: tuple[str, int] | None = None,
) -> dict[str, Any]:
    """Derive authorization holds from one consistent authority projection."""

    rows_by_cid: dict[str, Mapping[str, Any]] = {}
    cid_by_alias: dict[str, str] = {}
    for row in tasks:
        task_cid = str(row.get("task_cid") or "")
        alias = str(row.get("task_alias") or "")
        if not task_cid or not alias or task_cid in rows_by_cid or alias in cid_by_alias:
            raise RuntimeError("manual-gate hold projection has duplicate task identities")
        body = _decode_body(row)
        if str(body.get("task_id") or "") != alias:
            raise RuntimeError("manual-gate hold projection has a stale task body")
        rows_by_cid[task_cid] = row
        cid_by_alias[alias] = task_cid
    if not MANUAL_GATE_TASK_IDS.issubset(cid_by_alias):
        raise RuntimeError("manual-gate hold projection is missing a declared gate")

    dependents: dict[str, set[str]] = {task_cid: set() for task_cid in rows_by_cid}
    for row in dependencies:
        task_cid = str(row.get("task_cid") or "")
        dependency_cid = str(row.get("dependency_task_cid") or "")
        if (
            task_cid not in rows_by_cid
            or dependency_cid not in rows_by_cid
            or task_cid == dependency_cid
        ):
            raise RuntimeError("manual-gate hold projection has a foreign dependency")
        dependents[dependency_cid].add(task_cid)

    completed_events: dict[str, list[dict[str, Any]]] = {
        cid_by_alias[task_id]: [] for task_id in MANUAL_GATE_TASK_IDS
    }
    for row in sorted(events, key=lambda item: _safe_int(item.get("sequence"), 0)):
        task_cid = str(row.get("task_cid") or "")
        if task_cid not in completed_events or str(row.get("event_type") or "") != "status_changed":
            continue
        try:
            body = _strict_json_object(
                row.get("body_json"), noun=f"manual-gate event {row.get('event_cid') or '?'}"
            )
        except RuntimeError as exc:
            completed_events[task_cid].append({"invalid": str(exc)})
            continue
        if body.get("status") != "completed":
            continue
        if (
            body.get("schema") != _TASK_SOURCE_CAS_SCHEMA
            or body.get("task_cid") != task_cid
            or str(row.get("event_cid") or "") != _repository_content_identity(body)
        ):
            completed_events[task_cid].append(
                {"invalid": "manual-gate completed CAS event identity is invalid"}
            )
            continue
        completed_events[task_cid].append(body)

    gate_results: list[dict[str, Any]] = []
    incomplete_gate_cids: set[str] = set()
    for task_id in sorted(MANUAL_GATE_TASK_IDS):
        task_cid = cid_by_alias[task_id]
        row = rows_by_cid[task_cid]
        status = str(row.get("status") or "")
        verified = False
        detail = str(_decode_body(row).get("blocked_reason") or status)
        if status == "completed":
            current_revision = _safe_int(row.get("revision"), 0)
            candidates = [
                event
                for event in completed_events[task_cid]
                if _safe_int(event.get("task_revision"), 0) == current_revision
            ]
            if len(candidates) != 1 or "invalid" in candidates[0]:
                detail = "completed manual gate has no unique current typed CAS event"
            else:
                receipt = candidates[0].get("receipt")
                if not isinstance(receipt, Mapping):
                    detail = "completed manual gate has a bare CAS receipt"
                else:
                    verified, detail = _validate_manual_gate_cas_receipt(
                        receipt,
                        task_row=row,
                        snapshot=snapshot,
                        require_released=True,
                        materialization_receipts=materialization_receipts,
                        current_writer=current_writer,
                    )
        if not verified:
            incomplete_gate_cids.add(task_cid)
        gate_results.append(
            {
                "task_id": task_id,
                "task_cid": task_cid,
                "status": status,
                "authorization_verified": verified,
                "detail": detail,
            }
        )

    held_cids: set[str] = set()
    frontier = list(incomplete_gate_cids)
    while frontier:
        selected = frontier.pop()
        for dependent in dependents[selected]:
            if dependent not in held_cids:
                held_cids.add(dependent)
                frontier.append(dependent)
    held_aliases = tuple(sorted(str(rows_by_cid[item]["task_alias"]) for item in held_cids))
    held_digest = _manual_gate_receipt_id(
        "manual-gate-held-set",
        {
            "plan_root_cid": snapshot.plan_root_cid,
            "repository_tree_id": snapshot.repository_tree_id,
            "incomplete_gate_task_ids": sorted(
                item["task_id"]
                for item in gate_results
                if not item["authorization_verified"]
            ),
            "held_task_aliases": list(held_aliases),
        },
    )
    return {
        "gates": gate_results,
        "incomplete_gate_task_ids": tuple(
            item["task_id"]
            for item in gate_results
            if not item["authorization_verified"]
        ),
        "held_task_aliases": held_aliases,
        "held_set_sha256": held_digest,
    }


def _manual_gate_hold_projection(source: Any) -> tuple[Any, dict[str, Any]]:
    snapshot, tables, _counts = _consistent_rows(
        source,
        (
            "tasks",
            "task_dependencies",
            "task_events",
            "materialization_receipts",
        ),
    )
    return snapshot, _manual_gate_hold_projection_from_tables(
        snapshot,
        tables["tasks"],
        tables["task_dependencies"],
        tables["task_events"],
        tables["materialization_receipts"],
        _repository_task_source_writer(source),
    )


def _manual_gate_restart_admission(source: Any) -> tuple[bool, str]:
    try:
        lifecycle = _manual_gate_lifecycle_inspection()
        if not lifecycle["ok"]:
            return False, "launch_blocker=manual_gate_lifecycle_incomplete:" + (
                lifecycle["error"] or _canonical_json(lifecycle["incomplete"])
            )
        _snapshot, projection = _manual_gate_hold_projection(source)
        forged = [
            gate
            for gate in projection["gates"]
            if gate["status"] == "completed" and not gate["authorization_verified"]
        ]
        if forged:
            return False, "launch_blocker=manual_gate_authenticated_execution_missing:" + ";".join(
                f"{item['task_id']}={item['detail']}" for item in forged
            )
        return True, (
            f"authenticated_manual_gates={sum(item['authorization_verified'] for item in projection['gates'])}; "
            f"authorization_wait={','.join(projection['incomplete_gate_task_ids']) or 'none'}; "
            f"held_set={projection['held_set_sha256']}"
        )
    except Exception as exc:
        return False, f"manual-gate restart evidence rejected: {type(exc).__name__}: {exc}"


def _release_manual_gate_effect_leases(
    journal: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if journal.get("gate_task_id") != RELEASE_GATE_TASK_ID:
        return []
    records = journal.get("checkout_leases")
    prepared_at = str(journal.get("checkout_release_prepared_at") or "")
    if not isinstance(records, list) or not prepared_at:
        raise RuntimeError("DQK-056 checkout release has no prepared lease basis")
    return list(
        manual_gate_authority.release_checkout_leases(
            records,
            operation_id=str(journal["lifecycle_id"]),
            release_prepared_at=prepared_at,
            checkout_module=_manual_gate_checkout_module(),
            blob_store=_manual_gate_blob_store(),
        )
    )


def _manual_gate_checkout_release_set_id(
    journal: Mapping[str, Any], release: Sequence[Mapping[str, Any]]
) -> str:
    return _manual_gate_receipt_id(
        "manual-gate-checkout-release-set",
        {
            "lifecycle_id": journal["lifecycle_id"],
            "checkout_leases": list(journal.get("checkout_leases") or ()),
            "checkout_release": [dict(item) for item in release],
        },
    )


def _validate_manual_gate_checkout_release(journal: Mapping[str, Any]) -> str:
    releases = journal.get("checkout_release")
    if not isinstance(releases, list):
        raise RuntimeError("manual-gate checkout release evidence is missing")
    if journal.get("gate_task_id") != RELEASE_GATE_TASK_ID:
        if releases:
            raise RuntimeError("non-gitlink manual gate has checkout release evidence")
        return _manual_gate_checkout_release_set_id(journal, ())
    leases = journal.get("checkout_leases")
    if not isinstance(leases, list) or len(leases) != 2 or len(releases) != 2:
        raise RuntimeError("DQK-056 checkout release set is incomplete")
    basis_values = journal.get("checkout_lease_basis")
    if not isinstance(basis_values, list) or len(basis_values) != 2:
        raise RuntimeError("DQK-056 checkout acquisition basis is missing")
    validated_basis = []
    for item in basis_values:
        if not isinstance(item, Mapping):
            raise RuntimeError("DQK-056 checkout acquisition basis is untyped")
        validated_basis.append(
            manual_gate_authority.validate_checkout_lease_record(item)
        )
    validated_leases = []
    for item in leases:
        if not isinstance(item, Mapping):
            raise RuntimeError("DQK-056 checkout lease set is untyped")
        validated_leases.append(
            manual_gate_authority.validate_checkout_lease_record(item)
        )
    basis_by_id = {str(item["lease_id"]): item for item in validated_basis}
    leases_by_id = {
        str(item["lease_id"]): item for item in validated_leases
    }
    checkout_module = _manual_gate_checkout_module()
    expected_repositories = {
        "parent": REPO_ROOT.resolve(),
        "accelerator": ACCELERATE_ROOT.resolve(),
    }
    for lease in (*validated_basis, *validated_leases):
        role = str(lease["repository_role"])
        repository = expected_repositories.get(role)
        if repository is None:
            raise RuntimeError("DQK-056 checkout lease has an unknown role")
        expected_lock = os.path.abspath(
            os.fspath(checkout_module.checkout_mutation_lock_path(repository))
        )
        if (
            lease.get("repository_root") != str(repository)
            or lease.get("repository_id")
            != checkout_module.checkout_repository_id(repository)
            or lease.get("lock_path") != expected_lock
        ):
            raise RuntimeError(
                "DQK-056 checkout lease is outside the authoritative repositories"
            )
    if (
        len(leases_by_id) != 2
        or {str(item["repository_role"]) for item in validated_leases}
        != {"parent", "accelerator"}
        or len({str(item["lock_path"]) for item in validated_leases}) != 2
        or set(basis_by_id) != set(leases_by_id)
    ):
        raise RuntimeError("DQK-056 checkout lease set is malformed")
    for lease_id, lease in leases_by_id.items():
        manual_gate_authority.validate_checkout_lease_descendant(
            basis_by_id[lease_id], lease
        )
    intent = journal.get("effect_intent")
    lease_projection = [
        {
            key: item[key]
            for key in (
                "repository_role",
                "repository_id",
                "repository_root",
                "lock_path",
                "lease_id",
                "record_cid",
            )
        }
        for item in sorted(
            validated_basis, key=lambda value: str(value["repository_role"])
        )
    ]
    if (
        not isinstance(intent, Mapping)
        or sorted(
            [dict(item) for item in intent.get("checkout_lease_set") or ()],
            key=lambda value: str(value.get("repository_role") or ""),
        )
        != lease_projection
        or intent.get("checkout_lease_set_id")
        != manual_gate_authority.content_id(
            "manual-gate-checkout-lease-set",
            {"leases": list(intent.get("checkout_lease_set") or ())},
        )
    ):
        raise RuntimeError("DQK-056 effect intent is detached from its lease set")
    seen_release_ids: set[str] = set()
    for item in releases:
        if not isinstance(item, Mapping):
            raise RuntimeError("DQK-056 checkout release record shape is invalid")
        tombstone = item.get("tombstone")
        if not isinstance(tombstone, Mapping):
            raise RuntimeError("DQK-056 checkout release record is untyped")
        lease_id = str(tombstone.get("lease_id") or "")
        lease = leases_by_id.get(lease_id)
        if (
            lease is None
            or lease_id in seen_release_ids
            or tombstone.get("released_at")
            != journal.get("checkout_release_prepared_at")
        ):
            raise RuntimeError("DQK-056 checkout release tombstone is invalid")
        manual_gate_authority.validate_checkout_release_record(
            lease=lease,
            release=item,
            checkout_module=checkout_module,
            blob_store=_manual_gate_blob_store(),
        )
        seen_release_ids.add(lease_id)
    if seen_release_ids != set(leases_by_id):
        raise RuntimeError("DQK-056 checkout release set omits a lease")
    return _manual_gate_checkout_release_set_id(journal, releases)


def _manual_gate_release_receipt(
    journal: Mapping[str, Any], relaunch: Mapping[str, Any]
) -> dict[str, Any]:
    effect = journal.get("effect_receipt")
    execution = journal.get("execution")
    if not isinstance(effect, Mapping) or not isinstance(execution, Mapping):
        raise RuntimeError("manual-gate release lacks execution/effect authority")
    effect_id = str(effect.get("receipt_id") or effect.get("binding_id") or "")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", effect_id) is None:
        raise RuntimeError("manual-gate release effect identity is invalid")
    checkout_release_set_id = _validate_manual_gate_checkout_release(journal)
    receipt: dict[str, Any] = {
        "schema": MANUAL_GATE_RELEASE_RECEIPT_SCHEMA,
        "lifecycle_id": journal["lifecycle_id"],
        "gate_task_id": journal["gate_task_id"],
        "cas_receipt_id": journal["cas_receipt_id"],
        "execution_id": execution["execution_id"],
        "effect_receipt_id": effect_id,
        "checkout_release_set_id": checkout_release_set_id,
        "completed_task_revision": journal["completed_task_revision"],
        "relaunch": dict(relaunch),
        "released_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt["release_id"] = _manual_gate_receipt_id("manual-gate-release", receipt)
    return receipt


def _revalidate_released_manual_gate(
    journal: Mapping[str, Any],
    *,
    source: Any,
    task_row: Mapping[str, Any],
    snapshot: Any,
) -> dict[str, Any]:
    task_id = str(journal.get("gate_task_id") or "")
    task = source.get_task(task_id)
    cas_receipt = journal.get("cas_receipt")
    release = journal.get("release_receipt")
    if task is None or not isinstance(cas_receipt, Mapping) or not isinstance(
        release, Mapping
    ):
        raise RuntimeError("released manual-gate journal lacks authoritative records")
    authoritative = _authoritative_gate_receipt(source, task)
    if authoritative != dict(cas_receipt):
        raise RuntimeError("released manual gate no longer matches authoritative CAS")
    current_task_row = dict(task_row)
    current_task_row.update(
        {
            "task_alias": str(task.task_id),
            "task_cid": str(task.task_cid),
            "status": str(task.status),
            "revision": int(task.revision),
        }
    )
    materialization_receipts: tuple[Mapping[str, Any], ...] = ()
    if task_id == REFINEMENT_GATE_TASK_ID:
        projection = source.read_consistent_projection(("materialization_receipts",))
        materialization_receipts = tuple(
            projection.tables.get("materialization_receipts") or ()
        )
    valid, detail = _validate_manual_gate_cas_receipt(
        cas_receipt,
        task_row=current_task_row,
        snapshot=snapshot,
        require_released=True,
        materialization_receipts=materialization_receipts,
        current_writer=_repository_task_source_writer(source),
    )
    if not valid:
        raise RuntimeError(f"released manual-gate evidence failed replay: {detail}")
    return dict(release)


def _manual_gate_bound_mutator_identities() -> tuple[dict[str, Any], ...]:
    """Return every live datasets supervisor/daemon that could steal a lease."""

    markers = (
        "ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner",
        "implementation_supervisor_entry.py",
        "implementation_daemon",
    )
    bindings = (str(REPO_ROOT), str(RUNTIME_ROOT), str(MASTER_PID))
    matches: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        identity = _process_birth_identity(int(entry.name))
        if identity is None or _safe_int(identity.get("pid")) == os.getpid():
            continue
        command = "\0".join(str(item) for item in identity.get("argv") or ())
        if any(marker in command for marker in markers) and any(
            binding in command for binding in bindings
        ):
            matches.append(identity)
    return tuple(sorted(matches, key=lambda item: _safe_int(item.get("pid"))))


def _manual_gate_old_master() -> dict[str, Any] | None:
    pid = _read_pid(MASTER_PID)
    identity = _process_birth_identity(pid) if pid is not None else None
    if identity is None:
        return None
    valid, detail = _master_process_status(pid)
    if not valid:
        raise RuntimeError(f"manual-gate master identity is not authoritative: {detail}")
    session_id = _process_session_id(pid)
    if session_id is None or session_id == _process_session_id(os.getpid()):
        raise RuntimeError("manual-gate owner is not outside the master process session")
    return {**dict(identity), "dedicated_session_id": session_id}


def _manual_gate_runtime_drain_basis(lifecycle_id: str) -> dict[str, Any]:
    old_master = _manual_gate_old_master()
    process_tree: tuple[dict[str, Any], ...] = ()
    session_id = 0
    if old_master is not None:
        process_tree = _capture_process_tree(_safe_int(old_master.get("pid")))
        if any(_safe_int(item.get("pid")) == os.getpid() for item in process_tree):
            raise RuntimeError("manual-gate owner entered the drained process tree")
        session_id = _safe_int(old_master.get("dedicated_session_id"))
    else:
        unowned = _manual_gate_bound_mutator_identities()
        if unowned:
            raise RuntimeError(
                "manual-gate found live mutators without an authoritative master: "
                + ",".join(str(item["pid"]) for item in unowned)
            )
    record: dict[str, Any] = {
        "schema": MANUAL_GATE_DRAIN_SCHEMA,
        "lifecycle_id": lifecycle_id,
        "old_master": old_master,
        "old_process_tree": [dict(item) for item in process_tree],
        "old_session_id": session_id,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }
    record["drain_id"] = _manual_gate_receipt_id(
        "manual-gate-runtime-drain", record
    )
    return record


def _validate_manual_gate_runtime_drain(
    lifecycle_id: str, record: Mapping[str, Any]
) -> None:
    expected_keys = {
        "schema",
        "lifecycle_id",
        "old_master",
        "old_process_tree",
        "old_session_id",
        "prepared_at",
        "drain_id",
    }
    old_master = record.get("old_master")
    process_tree = record.get("old_process_tree")
    session_id = record.get("old_session_id")
    if (
        set(record) != expected_keys
        or record.get("schema") != MANUAL_GATE_DRAIN_SCHEMA
        or record.get("lifecycle_id") != lifecycle_id
        or record.get("drain_id")
        != _manual_gate_receipt_id(
            "manual-gate-runtime-drain",
            {key: value for key, value in record.items() if key != "drain_id"},
        )
        or not isinstance(process_tree, list)
        or not all(isinstance(item, Mapping) for item in process_tree)
        or isinstance(session_id, bool)
        or not isinstance(session_id, int)
        or session_id < 0
    ):
        raise RuntimeError("manual-gate runtime drain basis is malformed")
    prepared = datetime.fromisoformat(
        str(record.get("prepared_at") or "").replace("Z", "+00:00")
    )
    if prepared.tzinfo is None or prepared.utcoffset() is None:
        raise RuntimeError("manual-gate runtime drain timestamp is invalid")
    if old_master is None:
        if process_tree or session_id:
            raise RuntimeError("manual-gate empty drain claims a process tree")
        return
    if not isinstance(old_master, Mapping) or session_id <= 0 or not process_tree:
        raise RuntimeError("manual-gate runtime drain lacks master authority")
    if _safe_int(old_master.get("pid")) != _safe_int(process_tree[0].get("pid")):
        raise RuntimeError("manual-gate runtime drain root PID is detached")
    if _safe_int(old_master.get("dedicated_session_id")) != session_id:
        raise RuntimeError("manual-gate runtime drain session is detached")
    for identity in (old_master, *process_tree):
        if any(
            not identity.get(key)
            for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
        ):
            raise RuntimeError("manual-gate runtime drain has an unbound process")


def _drain_manual_gate_runtime(record: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle_id = str(record.get("lifecycle_id") or "")
    _validate_manual_gate_runtime_drain(lifecycle_id, record)
    old_master = record.get("old_master")
    if isinstance(old_master, Mapping) and _identity_is_live(old_master):
        pid = _safe_int(old_master.get("pid"))
        actual = _process_birth_identity(pid)
        if actual is None or any(
            actual.get(key) != old_master.get(key)
            for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
        ):
            raise RuntimeError("manual-gate master changed at the drain signal boundary")
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 60.0
    last_live: tuple[int, ...] = ()
    while time.monotonic() < deadline:
        captured = tuple(
            _safe_int(item.get("pid"))
            for item in record["old_process_tree"]
            if _identity_is_live(item)
        )
        session = (
            _process_session_members(_safe_int(record["old_session_id"]))
            if _safe_int(record["old_session_id"]) > 0
            else ()
        )
        mutators = tuple(
            _safe_int(item.get("pid"))
            for item in _manual_gate_bound_mutator_identities()
        )
        last_live = tuple(sorted(set((*captured, *session, *mutators))))
        if not last_live:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError(
            "manual-gate runtime did not quiesce: "
            + ",".join(str(pid) for pid in last_live)
        )
    drained: dict[str, Any] = {
        "schema": MANUAL_GATE_DRAIN_SCHEMA,
        "lifecycle_id": lifecycle_id,
        "drain_id": record["drain_id"],
        "quiescent_process_ids": [],
        "drained_at": datetime.now(timezone.utc).isoformat(),
    }
    drained["drained_id"] = _manual_gate_receipt_id(
        "manual-gate-runtime-drained", drained
    )
    return drained


def _validate_manual_gate_runtime_drained(
    lifecycle_id: str,
    basis: Mapping[str, Any],
    drained: Mapping[str, Any],
) -> None:
    _validate_manual_gate_runtime_drain(lifecycle_id, basis)
    if (
        set(drained)
        != {
            "schema",
            "lifecycle_id",
            "drain_id",
            "quiescent_process_ids",
            "drained_at",
            "drained_id",
        }
        or drained.get("schema") != MANUAL_GATE_DRAIN_SCHEMA
        or drained.get("lifecycle_id") != lifecycle_id
        or drained.get("drain_id") != basis.get("drain_id")
        or drained.get("quiescent_process_ids") != []
        or drained.get("drained_id")
        != _manual_gate_receipt_id(
            "manual-gate-runtime-drained",
            {
                key: value
                for key, value in drained.items()
                if key != "drained_id"
            },
        )
    ):
        raise RuntimeError("manual-gate drained receipt is malformed")
    timestamp = datetime.fromisoformat(
        str(drained.get("drained_at") or "").replace("Z", "+00:00")
    )
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise RuntimeError("manual-gate drained receipt timestamp is invalid")


def _same_process_birth(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256"))


def _start_manual_gate_checkout_custodian(
    journal: Mapping[str, Any],
) -> tuple[
    subprocess.Popen[bytes] | None,
    dict[str, Any] | None,
    tuple[dict[str, Any], ...],
]:
    """Start native-visible checkout custody for the effect lifecycle.

    The prior master and all implementation mutators have already drained.  A
    small isolated stdlib process becomes the compatibility owner before any
    effect is applied and remains so through CAS and master relaunch.  Thus a
    lifecycle-owner crash cannot expose a stale native lock.  The content-
    addressed lifecycle owner history remains the host-restart authority.
    """

    if journal.get("gate_task_id") != RELEASE_GATE_TASK_ID:
        return None, None, ()
    records = journal.get("checkout_leases")
    if not isinstance(records, list) or len(records) != 2:
        raise RuntimeError("DQK-056 has no exact checkout lease set for custody")
    command = (
        str(_trusted_base_python_path()),
        "-I",
        "-B",
        "-S",
        "-c",
        "import os,signal; signal.signal(signal.SIGTERM, lambda *_: os._exit(0)); signal.pause()",
        "dqk-manual-gate-checkout-custodian",
    )
    process: subprocess.Popen[bytes] = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    identity: dict[str, Any] | None = None
    identity_deadline = time.monotonic() + 2.0
    while time.monotonic() < identity_deadline and process.poll() is None:
        identity = _process_birth_identity(process.pid)
        if identity is not None and tuple(identity.get("argv") or ()) == command:
            break
        identity = None
        time.sleep(0.01)
    if identity is None:
        if process.poll() is None:
            process.terminate()
        raise RuntimeError("manual-gate checkout custodian did not become live")
    identity = {**identity, "argv": list(identity.get("argv") or ())}
    try:
        bound = manual_gate_authority.bind_checkout_leases_to_custodian(
            records,
            custodian=identity,
            owner_script=manual_gate_authority.compatibility_owner_script(identity),
            checkout_module=_manual_gate_checkout_module(),
        )
    except Exception:
        if process.poll() is None:
            process.terminate()
        raise
    _MANUAL_GATE_CUSTODIAN_PROCESSES[process.pid] = process
    return process, identity, bound


def _retire_manual_gate_checkout_custodian(
    identity: Mapping[str, Any] | None,
) -> None:
    if identity is None:
        return
    pid = _safe_int(identity.get("pid"))
    if pid < 1:
        raise RuntimeError("manual-gate checkout custodian PID is invalid")
    actual = _process_birth_identity(pid)
    if actual is None:
        _MANUAL_GATE_CUSTODIAN_PROCESSES.pop(pid, None)
        return
    if not _same_process_birth(actual, identity):
        # The exact process is already gone and the PID has been reused; never
        # signal the replacement.
        _MANUAL_GATE_CUSTODIAN_PROCESSES.pop(pid, None)
        return
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        current = _process_birth_identity(pid)
        if current is None or not _same_process_birth(current, identity):
            process = _MANUAL_GATE_CUSTODIAN_PROCESSES.pop(pid, None)
            if process is not None:
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            else:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except (ChildProcessError, OSError):
                    pass
            return
        time.sleep(0.02)
    raise RuntimeError("manual-gate checkout custodian did not terminate")


def _manual_gate_compatibility_custodian(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if len(records) != 2:
        raise RuntimeError("DQK-056 checkout custody requires exactly two leases")
    identities: list[dict[str, Any]] = []
    for record in records:
        validated = manual_gate_authority.validate_checkout_lease_record(record)
        owner = validated.get("compatibility_owner")
        if not isinstance(owner, Mapping):
            raise RuntimeError("DQK-056 checkout compatibility owner is missing")
        identity = {
            key: owner.get(key)
            for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")
        }
        if owner.get("owner_script") != manual_gate_authority.compatibility_owner_script(
            identity
        ):
            raise RuntimeError("DQK-056 checkout custodian is not native-visible")
        identities.append(identity)
    if not _same_process_birth(identities[0], identities[1]):
        raise RuntimeError("DQK-056 checkout leases have split custody")
    actual = _process_birth_identity(_safe_int(identities[0].get("pid")))
    return (
        {**actual, "argv": list(actual.get("argv") or ())}
        if actual is not None and _same_process_birth(actual, identities[0])
        else None
    )


def _ensure_manual_gate_effect_custody(
    journal: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any] | None]:
    if journal.get("gate_task_id") != RELEASE_GATE_TASK_ID:
        return (), None
    records = _acquire_or_adopt_manual_gate_effect_leases(journal)
    existing = _manual_gate_compatibility_custodian(records)
    if existing is not None and _safe_int(existing.get("pid")) != os.getpid():
        manual_gate_authority.assert_checkout_leases(
            records,
            checkout_module=_manual_gate_checkout_module(),
            expected_custodian=existing,
        )
        return records, existing
    _process, identity, bound = _start_manual_gate_checkout_custodian(
        {**dict(journal), "checkout_leases": list(records)}
    )
    if identity is None or len(bound) != 2:
        raise RuntimeError("DQK-056 checkout custodian was not established")
    manual_gate_authority.assert_checkout_leases(
        bound,
        checkout_module=_manual_gate_checkout_module(),
        expected_custodian=identity,
    )
    return bound, identity


def _manual_gate_relaunch_runtime(
    journal: Mapping[str, Any], source: Any
) -> dict[str, Any]:
    snapshot, execution_slice, slice_digest, _bootstrap_evidence_id = (
        _task_source_launch_contract(source)
    )
    if not execution_slice:
        return {
            "kind": "no-runnable-descendants",
            "plan_root_cid": snapshot.plan_root_cid,
            "repository_tree_id": snapshot.repository_tree_id,
            "execution_slice_sha256": slice_digest,
        }
    custodian_value = journal.get("checkout_custodian")
    custodian_identity = (
        dict(custodian_value) if isinstance(custodian_value, Mapping) else None
    )
    if journal.get("gate_task_id") == RELEASE_GATE_TASK_ID and (
        custodian_identity is None or not _identity_is_live(custodian_identity)
    ):
        raise RuntimeError("DQK-056 checkout custody ended before relaunch")
    old_master = journal.get("old_master")
    live = list(_live_program_master_identities())
    current_bound = [item for item in live if _actual_master_command_matches(item)]
    if len(current_bound) > 1:
        raise RuntimeError("multiple current-generation masters are live")
    if current_bound:
        identity = current_bound[0]
        result = {"kind": "adopted", **dict(identity)}
        _bind_manual_gate_relaunch_custodian(journal, result)
        if custodian_identity is not None and not _same_process_birth(
            custodian_identity, result
        ):
            _retire_manual_gate_checkout_custodian(custodian_identity)
        return result
    if isinstance(old_master, Mapping):
        old_live = next((item for item in live if _same_process_birth(item, old_master)), None)
        if old_live is not None:
            os.kill(int(old_live["pid"]), signal.SIGTERM)
            deadline = time.monotonic() + 60.0
            while _process_birth_identity(int(old_live["pid"])) is not None:
                if time.monotonic() >= deadline:
                    raise RuntimeError("old manual-gate execution-slice master did not drain")
                time.sleep(0.25)
    foreign = list(_live_program_master_identities())
    if foreign:
        raise RuntimeError("a foreign program master remains before manual-gate relaunch")
    lanes = _safe_int((old_master or {}).get("lane_count"), 2) if isinstance(old_master, Mapping) else 2
    if not 1 <= lanes <= MAX_IMPLEMENTATION_LANES:
        lanes = min(2, MAX_IMPLEMENTATION_LANES)
    launch_token = os.urandom(16).hex()
    command = supervisor_command(
        lanes=lanes,
        duration_seconds=float("inf"),
        detach=False,
        launch_token=launch_token,
    )
    environment = _scrubbed_sealed_process_environment()
    MASTER_ROOT.mkdir(parents=True, exist_ok=True)
    marker = _launch_marker()
    launcher_log = MASTER_ROOT / "launcher.out"
    with launcher_log.open("ab") as output_handle:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        pid = _bind_launched_master(
            snapshot,
            expected_command=command,
            marker=marker,
            expected_pid=process.pid,
        )
    except Exception:
        if process.poll() is None:
            process.terminate()
        raise
    identity = _process_birth_identity(pid)
    if identity is None:
        raise RuntimeError("manual-gate relaunched master disappeared")
    result = {"kind": "launched", **dict(identity)}
    # Transfer compatibility ownership before returning.  If the lifecycle
    # process dies before journaling RELAUNCHED, the live master remains a
    # daemon-recognized custodian and restart can rederive this exact transfer.
    _bind_manual_gate_relaunch_custodian(journal, result)
    if custodian_identity is not None and not _same_process_birth(
        custodian_identity, result
    ):
        _retire_manual_gate_checkout_custodian(custodian_identity)
    return result


def _run_manual_gate_lifecycle(
    task_id: str,
    *,
    receipt_file: Path,
    expected_task_revision: int,
    execute_verifier: Any = _execute_manual_gate_verifier,
    relaunch_runtime: Any = _manual_gate_relaunch_runtime,
) -> dict[str, Any]:
    if task_id not in MANUAL_GATE_TASK_IDS:
        raise RuntimeError(f"unsupported manual gate {task_id}")
    input_capture, raw_input = _manual_gate_input_capture(receipt_file)
    source = _source()
    snapshot, tasks, event_projection = _manual_gate_snapshot(source)
    gate_row = tasks.get(task_id)
    owner_row = tasks.get(MANUAL_GATE_OWNER_TASK_IDS[task_id])
    if gate_row is None or owner_row is None:
        raise RuntimeError("manual gate or its implementation owner is missing")
    task_cid = str(gate_row.get("task_cid") or "")
    with _manual_gate_lock_context():
        input_capture = _manual_gate_bound_input_capture(input_capture, raw_input)
        # Every replay consumes the immutable copy, not the caller-controlled
        # transport path after its initial nofollow capture.
        raw_input = _manual_gate_read_bound_input(input_capture)
        lifecycle_id = _manual_gate_lifecycle_id(
            task_id,
            task_cid=task_cid,
            snapshot=snapshot,
            input_capture=input_capture,
        )
        path = _manual_gate_journal_path(lifecycle_id)
        journal = (
            _read_manual_gate_journal(path)
            if path.exists() or path.is_symlink()
            else None
        )
        if journal is None:
            gate = source.get_task(task_id)
            owner = source.get_task(MANUAL_GATE_OWNER_TASK_IDS[task_id])
            if (
                gate is None
                or gate.task_cid != task_cid
                or gate.status != "blocked"
                or gate.revision != expected_task_revision
            ):
                raise RuntimeError("manual gate is not at the expected blocked CAS revision")
            if owner is None or owner.status != "completed":
                raise RuntimeError(
                    f"manual-gate owner {MANUAL_GATE_OWNER_TASK_IDS[task_id]} is not completed"
                )
            verifier = _manual_gate_verifier_attestation(task_id)
            interpreter = _manual_gate_interpreter_attestation()
            authority_adapter = _manual_gate_task_authority_adapter(task_id)
            decision_preflight = authority_adapter.preflight(
                task_id=task_id,
                raw_input=raw_input,
                snapshot=snapshot,
                verifier_attestation=verifier,
            )
            if not isinstance(decision_preflight, Mapping):
                raise RuntimeError(
                    "manual-gate signed-decision adapter returned no preflight proof"
                )
            identity = _repository_task_source_identity(source, snapshot)
            runtime_drain = _manual_gate_runtime_drain_basis(lifecycle_id)
            journal = {
                "schema": MANUAL_GATE_JOURNAL_SCHEMA,
                "lifecycle_id": lifecycle_id,
                "phase": "PREPARED",
                "program_id": PROGRAM_ID,
                "gate_task_id": task_id,
                "gate_task_cid": task_cid,
                "owner_task_id": MANUAL_GATE_OWNER_TASK_IDS[task_id],
                "authority_effect_id": MANUAL_GATE_AUTHORITY_EFFECT_IDS[task_id],
                "input_capture": input_capture,
                "plan_root_cid": snapshot.plan_root_cid,
                "repository_tree_id": snapshot.repository_tree_id,
                "task_source_identity_id": identity["identity_id"],
                "expected_task_revision": expected_task_revision,
                "verifier": verifier,
                "interpreter": interpreter,
                "decision_preflight": dict(decision_preflight),
                "old_master": runtime_drain["old_master"],
                "runtime_drain": runtime_drain,
                "prepared_at": datetime.now(timezone.utc).isoformat(),
            }
            journal = _write_manual_gate_journal(path, journal)
            journal["prepared_journal_cid"] = journal["journal_cid"]
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("PREPARED")
        elif journal["phase"] == "PREPARED" and not str(
            journal.get("prepared_journal_cid") or ""
        ):
            # Recover a process death between the initial fsynced PREPARED
            # publication and its self-reference-bearing successor.
            journal["prepared_journal_cid"] = journal["journal_cid"]
            journal = _write_manual_gate_journal(path, journal)
        immutable_bindings = {
            "schema": MANUAL_GATE_JOURNAL_SCHEMA,
            "lifecycle_id": lifecycle_id,
            "program_id": PROGRAM_ID,
            "gate_task_id": task_id,
            "gate_task_cid": task_cid,
            "owner_task_id": MANUAL_GATE_OWNER_TASK_IDS[task_id],
            "authority_effect_id": MANUAL_GATE_AUTHORITY_EFFECT_IDS[task_id],
            "input_capture": input_capture,
            "plan_root_cid": snapshot.plan_root_cid,
            "repository_tree_id": snapshot.repository_tree_id,
        }
        if any(journal.get(key) != value for key, value in immutable_bindings.items()):
            raise RuntimeError("manual-gate journal is stale or foreign")
        if (
            task_id == RELEASE_GATE_TASK_ID
            and journal["phase"]
            in {
                "EFFECT_PREPARED",
                "EFFECT_APPLIED",
                "CAS_COMMITTED",
            }
        ):
            recovered, custodian = _ensure_manual_gate_effect_custody(journal)
            if (
                list(recovered) != journal.get("checkout_leases")
                or dict(custodian or {}) != journal.get("checkout_custodian")
            ):
                journal["checkout_leases"] = list(recovered)
                journal["checkout_custodian"] = dict(custodian or {})
                journal = _write_manual_gate_journal(path, journal)
        if (
            task_id == RELEASE_GATE_TASK_ID
            and journal["phase"] == "RELAUNCHED"
        ):
            relaunch = journal.get("relaunch")
            if isinstance(relaunch, Mapping) and _identity_is_live(relaunch):
                recovered = list(
                    _bind_manual_gate_relaunch_custodian(journal, relaunch)
                )
                prior_custodian = journal.get("checkout_custodian")
                if (
                    isinstance(prior_custodian, Mapping)
                    and not _same_process_birth(prior_custodian, relaunch)
                ):
                    _retire_manual_gate_checkout_custodian(prior_custodian)
                custodian = dict(relaunch)
            else:
                held, custodian_value = _ensure_manual_gate_effect_custody(journal)
                recovered = list(held)
                custodian = dict(custodian_value or {})
            if (
                recovered != journal.get("checkout_leases")
                or custodian != journal.get("checkout_custodian")
            ):
                journal["checkout_leases"] = recovered
                journal["checkout_custodian"] = custodian
                journal = _write_manual_gate_journal(path, journal)
        if journal["phase"] == "RELEASED":
            return _revalidate_released_manual_gate(
                journal,
                source=source,
                task_row=gate_row,
                snapshot=snapshot,
            )
        if journal["phase"] == "PREPARED":
            _validate_manual_gate_runtime_drain(
                lifecycle_id, journal["runtime_drain"]
            )
            journal["phase"] = "DRAIN_PREPARED"
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("DRAIN_PREPARED")
        if journal["phase"] == "DRAIN_PREPARED":
            journal["runtime_drained"] = _drain_manual_gate_runtime(
                journal["runtime_drain"]
            )
            journal["phase"] = "DRAINED"
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("DRAINED")
        if journal["phase"] == "DRAINED":
            _validate_manual_gate_runtime_drained(
                lifecycle_id,
                journal["runtime_drain"],
                journal["runtime_drained"],
            )
            # Publish intent before invoking even a read-only verifier.  The
            # task-owned 102/103 adapters remain unavailable, so those gates
            # reject above before this transition and before subprocess use.
            journal["phase"] = "EXECUTION_PREPARED"
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("EXECUTION_PREPARED")
        if journal["phase"] == "EXECUTION_PREPARED":
            execution = execute_verifier(
                task_id,
                raw_input=raw_input,
                input_capture=input_capture,
                snapshot=snapshot,
                verifier_attestation=journal["verifier"],
                interpreter_attestation=journal["interpreter"],
                decision_preflight=journal["decision_preflight"],
            )
            _validate_manual_gate_execution_receipt(
                task_id,
                execution,
                snapshot=snapshot,
                input_capture=input_capture,
            )
            journal["execution"] = execution
            acquired = list(_acquire_or_adopt_manual_gate_effect_leases(journal))
            journal["checkout_leases"] = acquired
            held, custodian = _ensure_manual_gate_effect_custody(journal)
            journal["checkout_leases"] = list(held)
            journal["checkout_custodian"] = dict(custodian or {})
            journal["checkout_lease_basis"] = [dict(item) for item in held]
            journal["effect_intent"] = _prepare_manual_gate_effect(
                task_id,
                journal=journal,
                execution=execution,
                source=source,
                snapshot=snapshot,
            )
            journal["phase"] = "EFFECT_PREPARED"
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("EFFECT_PREPARED")
        if journal["phase"] == "EFFECT_PREPARED":
            effect_receipt = _apply_manual_gate_effect(
                task_id,
                journal=journal,
                execution=journal["execution"],
                source=source,
                snapshot=snapshot,
            )
            journal["effect_receipt"] = effect_receipt
            journal["cas_receipt"] = _manual_gate_cas_receipt(
                journal, journal["execution"], effect_receipt
            )
            journal["phase"] = "EFFECT_APPLIED"
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("EFFECT_APPLIED")
        if journal["phase"] == "EFFECT_APPLIED":
            cas_receipt = journal.get("cas_receipt")
            if not isinstance(cas_receipt, Mapping):
                raise RuntimeError("effect-applied journal has no manual-gate CAS receipt")
            gate = source.get_task(task_id)
            if gate is None:
                raise RuntimeError("manual gate disappeared before CAS")
            if gate.status == "blocked" and gate.revision == expected_task_revision:
                result = source.compare_and_set_status(
                    task_id,
                    expected_revision=gate.revision,
                    status="completed",
                    receipt=cas_receipt,
                )
                _manual_gate_crash_boundary("CAS_COMMITTED")
                gate = result.task
            if gate.status != "completed" or gate.revision != expected_task_revision + 1:
                raise RuntimeError("manual gate CAS is stale or was completed by another receipt")
            authoritative = _authoritative_gate_receipt(source, gate)
            if authoritative != dict(cas_receipt):
                raise RuntimeError("manual gate was completed by a bare or foreign CAS")
            journal["cas_receipt_id"] = cas_receipt["receipt_id"]
            journal["completed_task_revision"] = gate.revision
            journal["phase"] = "CAS_COMMITTED"
            journal = _write_manual_gate_journal(path, journal)
        if journal["phase"] == "CAS_COMMITTED":
            _assert_manual_gate_effect_leases(journal)
            prior_custodian = journal.get("checkout_custodian")
            relaunch = relaunch_runtime(journal, source)
            journal["checkout_leases"] = list(
                _bind_manual_gate_relaunch_custodian(journal, relaunch)
            )
            if (
                isinstance(relaunch, Mapping)
                and _safe_int(relaunch.get("pid")) > 0
                and _identity_is_live(relaunch)
            ):
                if (
                    isinstance(prior_custodian, Mapping)
                    and not _same_process_birth(prior_custodian, relaunch)
                ):
                    _retire_manual_gate_checkout_custodian(prior_custodian)
                journal["checkout_custodian"] = dict(relaunch)
            _manual_gate_crash_boundary("RELAUNCHED")
            journal["relaunch"] = relaunch
            journal["phase"] = "RELAUNCHED"
            journal = _write_manual_gate_journal(path, journal)
        if journal["phase"] == "RELAUNCHED":
            _assert_manual_gate_effect_leases(journal)
            journal["checkout_release_prepared_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            journal["phase"] = "RELEASE_PREPARED"
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("RELEASE_PREPARED")
        if journal["phase"] == "RELEASE_PREPARED":
            journal["checkout_release"] = _release_manual_gate_effect_leases(journal)
            custodian = journal.get("checkout_custodian")
            relaunch = journal.get("relaunch")
            if (
                task_id == RELEASE_GATE_TASK_ID
                and isinstance(custodian, Mapping)
                and _safe_int(custodian.get("pid")) > 0
                and (
                    not isinstance(relaunch, Mapping)
                    or _safe_int(relaunch.get("pid")) < 1
                    or not _same_process_birth(custodian, relaunch)
                )
            ):
                _retire_manual_gate_checkout_custodian(custodian)
            release = _manual_gate_release_receipt(journal, journal["relaunch"])
            journal["release_receipt"] = release
            journal["phase"] = "RELEASED"
            journal = _write_manual_gate_journal(path, journal)
            _manual_gate_crash_boundary("RELEASED")
        return _revalidate_released_manual_gate(
            journal,
            source=source,
            task_row=tasks[task_id],
            snapshot=snapshot,
        )


def _bounded_json_file(
    path: Path,
    *,
    max_bytes: int = 2 * 1024 * 1024,
) -> tuple[dict[str, Any], str, bytes]:
    raw = _read_nofollow_bounded_file(path, max_bytes=max_bytes)
    try:
        payload = _strict_json_object(
            raw.decode("utf-8", errors="strict"), noun="receipt transport"
        )
    except UnicodeDecodeError as exc:
        raise RuntimeError("receipt transport is not UTF-8") from exc
    return payload, f"sha256:{hashlib.sha256(raw).hexdigest()}", raw


def _head_gitlink_commit(path: str) -> str:
    record = _git("ls-tree", "HEAD", "--", path)
    fields = record.split()
    if len(fields) < 3 or fields[0] != "160000" or fields[1] != "commit":
        raise RuntimeError(f"HEAD does not contain the expected gitlink {path}")
    return fields[2]


def _authoritative_gate_receipt(source: Any, task: Any) -> dict[str, Any] | None:
    _snapshot, tables, _counts = _consistent_rows(source, ("task_events",))
    return _latest_status_receipt(
        tables["task_events"],
        task_cid=str(task.task_cid),
        status="completed",
    )


def cmd_ack_release(args: argparse.Namespace) -> int:
    release = _run_manual_gate_lifecycle(
        RELEASE_GATE_TASK_ID,
        receipt_file=Path(args.receipt),
        expected_task_revision=args.expected_task_revision,
    )
    print(_canonical_json(release))
    return 0


def cmd_ack_refinement(args: argparse.Namespace) -> int:
    release = _run_manual_gate_lifecycle(
        REFINEMENT_GATE_TASK_ID,
        receipt_file=Path(args.receipt),
        expected_task_revision=args.expected_task_revision,
    )
    print(_canonical_json(release))
    return 0


def cmd_ack_promotion(args: argparse.Namespace) -> int:
    release = _run_manual_gate_lifecycle(
        PROMOTION_GATE_TASK_ID,
        receipt_file=Path(args.receipt),
        expected_task_revision=args.expected_task_revision,
    )
    print(_canonical_json(release))
    return 0


def cmd_ack_runtime_activation(args: argparse.Namespace) -> int:
    release = _run_manual_gate_lifecycle(
        RUNTIME_ACTIVATION_GATE_TASK_ID,
        receipt_file=Path(args.receipt),
        expected_task_revision=args.expected_task_revision,
    )
    print(_canonical_json(release))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    source = _source()
    if args.format == "markdown":
        rendered = render_markdown(source)
    else:
        rendered = json.dumps(database_projection(source), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    selected_output = args.output
    if selected_output is None:
        selected_output = str(
            DEFAULT_MARKDOWN_EXPORT if args.format == "markdown" else DEFAULT_JSON_EXPORT
        )
    if selected_output == "-":
        sys.stdout.write(rendered)
        return 0
    requested_path = Path(selected_output).expanduser()
    if not requested_path.is_absolute():
        requested_path = Path.cwd() / requested_path
    if requested_path.is_symlink():
        raise RuntimeError("refusing to replace a symlink export destination")
    output_path = requested_path.parent.resolve() / requested_path.name
    if output_path.exists() and not output_path.is_file():
        raise RuntimeError("export destination exists and is not a regular file")
    recognized_projection = False
    if output_path.is_file() and output_path.stat().st_size <= 16 * 1024 * 1024:
        existing = output_path.read_text(encoding="utf-8", errors="replace")
        if "Generated projection only" in existing and "rendered-body-sha256" in existing:
            recognized_projection = True
        else:
            try:
                existing_payload = json.loads(existing)
            except json.JSONDecodeError:
                existing_payload = None
            recognized_projection = bool(
                isinstance(existing_payload, dict)
                and existing_payload.get("schema")
                == "ipfs_datasets_py/duckdb-quack-plan-export@1"
            )
    default_destinations = {
        DEFAULT_MARKDOWN_EXPORT.resolve(),
        DEFAULT_JSON_EXPORT.resolve(),
    }
    if (
        output_path not in default_destinations
        and not recognized_projection
        and not bool(getattr(args, "force", False))
    ):
        raise RuntimeError(
            "arbitrary export destinations require --force unless they already "
            "contain a recognized generated projection"
        )
    _atomic_write_text(output_path, rendered)
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    print(f"wrote {args.format} export to {output_path} (sha256:{digest})")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    checks = preflight_checks(require_clean=not args.allow_dirty)
    if args.json:
        print(json.dumps(checks, indent=2, sort_keys=True))
    else:
        _print_checks(checks)
    return 0 if all(check["ok"] or not check["required"] for check in checks) else 2


def _task_source_roots(source: Any) -> tuple[str, str]:
    snapshot = source.snapshot()
    return snapshot.plan_root_cid, snapshot.repository_tree_id


def _task_source_launch_contract(
    source: Any,
) -> tuple[Any, tuple[str, ...], str, str]:
    """Read one immutable generation and derive its bounded execution slice.

    The seed ``TASKS`` tuple only bootstraps generation zero.  After a governed
    rollover, task selection must come from the accepted DuckDB generation so
    added and retired tasks cannot be hidden by this wrapper's source code.
    """

    projection = source.read_consistent_projection(
        ("tasks", "task_dependencies", "task_events", "materialization_receipts")
    )
    snapshot = projection.snapshot
    aliases: list[str] = []
    seen_aliases: set[str] = set()
    rows = tuple(projection.tables.get("tasks") or ())
    if int(projection.row_counts.get("tasks", -1)) != len(rows):
        raise RuntimeError("launch task projection row count mismatch")
    for row in rows:
        alias = str(row.get("task_alias") or "").strip()
        task_cid = str(row.get("task_cid") or "").strip()
        body = _decode_body(row)
        if not alias or not task_cid or alias in seen_aliases:
            raise RuntimeError("launch task projection has an invalid identity")
        if str(body.get("task_id") or "") != alias:
            raise RuntimeError("launch task alias/body identity mismatch")
        seen_aliases.add(alias)
        if bool(body.get("is_schedulable", True)):
            aliases.append(alias)
    bootstrap = next(
        (
            row
            for row in rows
            if str(row.get("task_alias") or "") == BOOTSTRAP_TASK_ID
        ),
        None,
    )
    bootstrap_completion_evidence_id = ""
    if bootstrap is not None and str(bootstrap.get("status") or "") == "completed":
        (
            bridge_receipt_valid,
            bridge_receipt_detail,
            bootstrap_completion_evidence_id,
        ) = (
            _bootstrap_bridge_receipt_contract(
                source,
                snapshot,
                rows,
                tuple(projection.tables.get("task_events") or ()),
            )
        )
        if not bridge_receipt_valid:
            raise RuntimeError(
                f"cannot trust completed {BOOTSTRAP_TASK_ID} at launch: "
                + bridge_receipt_detail
            )
    hold_projection = _manual_gate_hold_projection_from_tables(
        snapshot,
        rows,
        tuple(projection.tables.get("task_dependencies") or ()),
        tuple(projection.tables.get("task_events") or ()),
        tuple(projection.tables.get("materialization_receipts") or ()),
        _repository_task_source_writer(source),
    )
    held_aliases = set(hold_projection["held_task_aliases"])
    aliases = [alias for alias in aliases if alias not in held_aliases]
    if not aliases or len(aliases) > 8192:
        raise RuntimeError("launch execution slice is empty or exceeds its bound")
    aliases.sort()
    if MANUAL_GATE_TASK_IDS.intersection(aliases):
        raise RuntimeError("manual receipt gates cannot enter the execution slice")
    digest = _execution_slice_digest(
        plan_root_cid=str(snapshot.plan_root_cid),
        repository_tree_id=str(snapshot.repository_tree_id),
        task_aliases=aliases,
        held_task_aliases=hold_projection["held_task_aliases"],
        held_set_sha256=hold_projection["held_set_sha256"],
    )
    return snapshot, tuple(aliases), digest, bootstrap_completion_evidence_id


def cmd_smoke(args: argparse.Namespace) -> int:
    source = _source()
    plan_root, repository_root = _task_source_roots(source)
    source.validate_integrity()
    projection = source.read_consistent_projection(
        ("goals", "tasks", "task_dependencies", "task_events")
    )
    # Exercise the same runner topology as both launch modes.  Detached launch
    # is external session detachment of this wrapper process; the runner's own
    # ``--detach`` reconstruction is deliberately never part of DQK launch.
    command = supervisor_command(lanes=2, duration_seconds=60, detach=False)
    if args.dry_run:
        print(shlex.join(command))
        return 0
    from ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner import (
        build_arg_parser,
        common_args_from_parsed_args,
        tracks_from_parsed_args,
    )
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
        parse_args as parse_daemon_args,
    )
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor import (
        PortalImplementationSupervisor,
        parse_args as parse_supervisor_args,
        supervisor_config_from_args,
    )

    runner_args = build_arg_parser().parse_args(command[3:])
    common = common_args_from_parsed_args(runner_args)
    rendered_children: list[list[str]] = []
    completed_bootstrap = any(
        str(row.get("task_alias") or "") == BOOTSTRAP_TASK_ID
        and str(row.get("status") or "") == "completed"
        for row in projection.tables.get("tasks") or ()
    )
    expected_bootstrap_evidence_id = ""
    if completed_bootstrap:
        _valid, _detail, expected_bootstrap_evidence_id = (
            _bootstrap_bridge_receipt_contract(
                source,
                projection.snapshot,
                tuple(projection.tables.get("tasks") or ()),
                tuple(projection.tables.get("task_events") or ()),
            )
        )
    for track in tracks_from_parsed_args(runner_args):
        supervisor_args = parse_supervisor_args([*common, *track.extra_args])
        config = supervisor_config_from_args(supervisor_args, repo_root=REPO_ROOT)
        daemon_command = PortalImplementationSupervisor(config)._build_daemon_command()
        daemon_args = parse_daemon_args(daemon_command[3:])
        if (
            daemon_args.task_source_kind != "duckdb"
            or daemon_args.expected_task_source_root != plan_root
            or daemon_args.expected_task_source_repository_root != repository_root
            or daemon_args.assume_completed_task_id
            or daemon_args.duckdb_bootstrap_completion_evidence_id
            != (
                [expected_bootstrap_evidence_id]
                if expected_bootstrap_evidence_id
                else []
            )
            or MANUAL_GATE_TASK_IDS.intersection(
                daemon_args.execution_slice_task_id
            )
        ):
            raise RuntimeError("supervisor-to-daemon canonical source contract mismatch")
        rendered_children.append(daemon_command)
    print(
        json.dumps(
            {
                "schema": "ipfs_datasets_py/duckdb-quack-smoke-probe@1",
                "plan_root_cid": projection.snapshot.plan_root_cid,
                "repository_tree_id": projection.snapshot.repository_tree_id,
                "revision": projection.snapshot.revision,
                "row_counts": dict(projection.row_counts),
                "lane_count": len(rendered_children),
                "mutated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _implementation_protected_paths() -> tuple[str, ...]:
    return (
        str(Path(__file__).resolve().relative_to(REPO_ROOT)),
        str(MANUAL_GATE_AUTHORITY_MODULE.relative_to(REPO_ROOT)),
        str(BOOTSTRAP_REQUIREMENTS.relative_to(REPO_ROOT)),
        ".gitignore",
        str(DEFAULT_MARKDOWN_EXPORT.relative_to(REPO_ROOT)),
    )


def supervisor_command(
    *,
    lanes: int,
    duration_seconds: float,
    detach: bool,
    launch_token: str = "",
) -> list[str]:
    source = _source()
    (
        launch_snapshot,
        execution_slice,
        _slice_digest,
        bootstrap_completion_evidence_id,
    ) = _task_source_launch_contract(source)
    plan_root = str(launch_snapshot.plan_root_cid)
    repository_root = str(launch_snapshot.repository_tree_id)
    entry = ACCELERATE_ROOT / "scripts/ops/agent_supervisor/implementation_supervisor_entry.py"
    state_spec = f"dqk|{entry}|{STATE_ROOT}|dqk"
    common_args = [
        "--implement",
        "--todo-path",
        str(DATABASE_PATH),
        "--task-source-kind",
        "duckdb",
        "--expected-task-source-root",
        plan_root,
        "--expected-task-source-repository-root",
        repository_root,
        "--task-prefix",
        "DQK-",
        "--stale-seconds",
        "7500",
        "--check-interval",
        "30",
        "--watchdog-startup-grace-seconds",
        "420",
        "--max-restarts",
        "10",
        "--max-task-attempts",
        "4",
        "--daemon-interval",
        "30",
        "--managed-python-executable",
        str(SEALED_PYTHON_LAUNCHER),
        "--implementation-timeout",
        "7200",
        "--implementation-max-timeout",
        "7200",
        "--implementation-log-stall-seconds",
        "900",
        "--worktree-root",
        str(WORKTREE_ROOT),
        "--merge-target-branch",
        TARGET_BRANCH,
        "--merge-queue-dir",
        str(MERGE_QUEUE_ROOT),
        "--merge-reconciliation-max-merges",
        "1",
        "--worktree-reconciliation-max-merges",
        "1",
        "--worktree-submodule-path",
        "ipfs_accelerate_py",
        "--no-retry-budget-guardrail",
        "--no-dependency-guardrail",
        "--no-reconciliation-guardrail",
        "--no-objective-task-janitor",
        "--no-objective-goal-completion-reconcile",
        "--no-objective-goal-migration",
    ]
    for protected_path in _implementation_protected_paths():
        common_args.extend(["--implementation-protected-path", protected_path])
    if bootstrap_completion_evidence_id:
        common_args.extend(
            [
                "--duckdb-bootstrap-completion-evidence-id",
                bootstrap_completion_evidence_id,
            ]
        )
    for task_alias in execution_slice:
        common_args.extend(["--execution-slice-task-id", task_alias])
    if launch_token and re.fullmatch(r"[0-9a-f]{32}", launch_token) is None:
        raise ValueError("launch token must be a 128-bit lowercase hexadecimal value")
    stamp = f"dqk-{plan_root.rsplit(':', 1)[-1][:12]}"
    if launch_token:
        stamp += f"-{launch_token}"
    command = [
        str(SEALED_PYTHON_LAUNCHER),
        "-m",
        "ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner",
        "--repo-root",
        str(REPO_ROOT),
        "--duration-seconds",
        str(duration_seconds),
        "--heartbeat-interval-seconds",
        "30",
        "--supervisor-status-stale-seconds",
        "600",
        "--stop-grace-seconds",
        "30",
        "--stamp",
        stamp,
        "--master-dir",
        str(MASTER_ROOT),
        "--master-log",
        str(MASTER_LOG),
        "--master-pid-path",
        str(MASTER_PID),
        "--label",
        PROGRAM_ID,
        "--python-executable",
        str(SEALED_PYTHON_LAUNCHER),
        "--implementation-track",
        state_spec,
        "--implementation-supervisor-lanes-per-track",
        str(max(1, lanes)),
    ]
    command.extend(f"--common-arg={item}" for item in common_args)
    if detach:
        command.append("--detach")
    return command


def _launch_marker() -> dict[str, Any]:
    """Capture the evidence needed to distinguish this launch from a PID race."""

    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
        ticks_per_second = int(os.sysconf("SC_CLK_TCK"))
        start_ticks_floor = int(
            time.clock_gettime(time.CLOCK_BOOTTIME) * ticks_per_second
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("cannot capture process-birth launch marker") from exc
    before: dict[str, Any] | None = None
    try:
        stat_result = MASTER_PID.lstat()
        before = {
            "device": stat_result.st_dev,
            "inode": stat_result.st_ino,
            "mtime_ns": stat_result.st_mtime_ns,
            "size": stat_result.st_size,
            "value": MASTER_PID.read_text(encoding="utf-8", errors="strict"),
        }
    except OSError:
        pass
    return {
        "boot_id": boot_id,
        "start_ticks_floor": start_ticks_floor,
        "wall_time_ns": time.time_ns(),
        "pidfile_before": before,
    }


def _pidfile_was_published_for_launch(marker: Mapping[str, Any]) -> bool:
    """Require a new regular PID-file publication after the launch marker."""

    import stat

    try:
        current = MASTER_PID.lstat()
        if not stat.S_ISREG(current.st_mode) or MASTER_PID.is_symlink():
            return False
        signature = {
            "device": current.st_dev,
            "inode": current.st_ino,
            "mtime_ns": current.st_mtime_ns,
            "size": current.st_size,
            "value": MASTER_PID.read_text(encoding="utf-8", errors="strict"),
        }
    except OSError:
        return False
    return bool(
        signature != marker.get("pidfile_before")
        and signature["mtime_ns"] >= int(marker.get("wall_time_ns") or 0)
    )


def _launched_identity_matches(
    identity: Mapping[str, Any] | None,
    *,
    expected_command: Sequence[str],
    marker: Mapping[str, Any],
    expected_pid: int | None = None,
) -> bool:
    if not _process_identity_matches_sealed_command(identity, expected_command):
        return False
    assert identity is not None
    if expected_pid is not None and identity.get("pid") != expected_pid:
        return False
    pid = _safe_int(identity.get("pid"))
    if _process_python_environment(pid) != _sealed_python_environment():
        return False
    return bool(
        identity.get("boot_id") == marker.get("boot_id")
        and _safe_int(identity.get("start_ticks"))
        >= _safe_int(marker.get("start_ticks_floor"))
        and _pidfile_was_published_for_launch(marker)
    )


def _bind_launched_master(
    snapshot: Any,
    *,
    expected_command: Sequence[str],
    marker: Mapping[str, Any],
    expected_pid: int | None = None,
    timeout_seconds: float = 20.0,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    last_reason = "pid_not_written"
    while time.monotonic() < deadline:
        pid = _read_pid(MASTER_PID)
        actual = _process_birth_identity(pid) if pid is not None else None
        if _launched_identity_matches(
            actual,
            expected_command=expected_command,
            marker=marker,
            expected_pid=expected_pid,
        ):
            _write_master_identity(pid, snapshot)
            bound, reason = _master_process_status(
                pid,
                expected_plan_root=snapshot.plan_root_cid,
                expected_repository_root=snapshot.repository_tree_id,
            )
            if bound:
                return pid
            last_reason = reason
        elif pid is not None and _pid_exists(pid):
            last_reason = "pidfile_points_to_foreign_live_process"
        time.sleep(0.25)
    raise RuntimeError(f"could not bind launched master identity: {last_reason}")


def cmd_launch(args: argparse.Namespace) -> int:
    checks = preflight_checks(require_clean=True)
    _print_checks(checks)
    failures = [check for check in checks if check["required"] and not check["ok"]]
    if failures:
        print("launch refused: required preflight checks failed", file=sys.stderr)
        return 2
    launch_token = os.urandom(16).hex()
    command = supervisor_command(
        lanes=args.lanes,
        duration_seconds=args.duration_seconds,
        # The accelerator runner's built-in detach path reconstructs itself
        # with ``sys.executable`` and would discard the sealed wrapper.  This
        # lifecycle owner detaches the exact wrapper process below instead.
        detach=False,
        launch_token=launch_token,
    )
    print("launch command:", shlex.join(command))
    if args.dry_run:
        return 0
    MASTER_ROOT.mkdir(parents=True, exist_ok=True)
    environment = _scrubbed_sealed_process_environment()
    environment.setdefault("IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER", "auto")
    snapshot = _source().snapshot()
    marker = _launch_marker()
    if args.foreground:
        process = subprocess.Popen(command, cwd=REPO_ROOT, env=environment)
        try:
            _bind_launched_master(
                snapshot,
                expected_command=command,
                marker=marker,
                expected_pid=process.pid,
            )
        except Exception:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=30)
            raise
        return int(process.wait())
    launcher_log = MASTER_ROOT / "launcher.out"
    with launcher_log.open("ab") as output_handle:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        _bind_launched_master(
            snapshot,
            expected_command=command,
            marker=marker,
            expected_pid=process.pid,
        )
    except Exception:
        launched_pid = process.pid
        launched_identity = _process_birth_identity(launched_pid)
        process_was_launched = _launched_identity_matches(
            launched_identity,
            expected_command=command,
            marker=marker,
            expected_pid=process.pid,
        )
        # ``process`` is the exact Popen handle created by this invocation, so
        # it is safe to terminate even when PID-file publication never became
        # complete enough for authoritative identity binding.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
        failure_receipt = {
            "schema": "ipfs_datasets_py/duckdb-quack-launch-failure@1",
            "program_id": PROGRAM_ID,
            "plan_root_cid": snapshot.plan_root_cid,
            "repository_tree_id": snapshot.repository_tree_id,
            "pid": launched_pid,
            "process_was_command_bound": process_was_launched,
            "launch_token_sha256": (
                f"sha256:{hashlib.sha256(launch_token.encode()).hexdigest()}"
            ),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_write_text(
            MASTER_ROOT / "launch-failure.json",
            json.dumps(failure_receipt, indent=2, sort_keys=True) + "\n",
        )
        raise
    payload = task_status(_source())
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not args.foreground and not payload["master_alive"]:
        print("detached master did not remain alive", file=sys.stderr)
        return 3
    return 0


def cmd_retry_preview(args: argparse.Namespace) -> int:
    with _environment_lifecycle_lock(exclusive=False):
        preview = retry_lifecycle_preview(args.request_file)
    print(
        json.dumps(
            preview,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_recover_task(args: argparse.Namespace) -> int:
    # Hold the shared environment generation continuously.  The old master
    # holds the same lock before drain and the new sealed wrapper acquires it
    # before this owner releases it, leaving no mutation window between them.
    with _environment_lifecycle_lock(exclusive=False):
        receipt = _run_retry_lifecycle(
            args.request_file,
            drain_timeout_seconds=args.drain_timeout_seconds,
        )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = task_status(_source())
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(
        f"program={payload['program_id']} revision={payload['revision']} "
        f"tasks={payload['terminal_count']}/{payload['task_count']} terminal "
        f"master={'live' if payload['master_alive'] else 'not-live'} pid={payload['master_pid']}"
    )
    print("statuses=" + ", ".join(f"{key}:{value}" for key, value in payload["status_counts"].items()))
    for lane in payload["lane_status"]:
        print(
            f"lane={Path(lane['path']).parent.name} age={lane['age_seconds']}s "
            f"status={lane['status']} active={lane['active_task_id'] or '-'} "
            f"phase={lane['active_phase'] or '-'} heartbeat_age={lane['heartbeat_age_seconds']}s"
        )
    print(f"master_log={payload['master_log']}")
    return 0


def _external_dqp_status() -> dict[str, Any]:
    configured = os.environ.get("IPFS_DATASETS_DQP_ROOT", "").strip()
    root = (
        Path(configured).resolve()
        if configured
        else REPO_ROOT.parents[1] / ".worktrees/duckdb-quack-control-plane"
    )
    runtime = root / "state/agent_supervisor_duckdb_quack_control_plane"
    pid_path = runtime / "state/configured-board-master.pid"
    pid = _read_pid(pid_path)
    actual = _process_birth_identity(pid) if pid is not None else None
    argv = tuple(str(item) for item in (actual or {}).get("argv") or ())
    master_alive = bool(
        actual
        and "ipfs_accelerate_py.agent_supervisor.runtime.multi_supervisor_runner"
        in argv
        and _option_value(argv, "--repo-root") == str(root)
        and _option_value(argv, "--label")
        == "agent-supervisor-duckdb-quack-control-plane-v1"
        and _option_value(argv, "--master-pid-path") == str(pid_path)
    )
    now = time.time()
    lane_rows: list[dict[str, Any]] = []
    for status_path in sorted(
        runtime.glob("state/lane-*/*_supervisor_status.json")
    ):
        status_payload = _read_json_object(status_path)
        state_path = Path(str(status_payload.get("state_path") or ""))
        if not state_path.is_absolute():
            state_path = root / state_path
        state_payload = _read_json_object(state_path)
        active_log_value = str(state_payload.get("active_log_path") or "")
        active_log_path = Path(active_log_value) if active_log_value else None
        if active_log_path is not None and not active_log_path.is_absolute():
            active_log_path = root / active_log_path
        active_log_stat = (
            active_log_path.stat()
            if active_log_path is not None and active_log_path.is_file()
            else None
        )
        daemon_pid = _safe_int(status_payload.get("daemon_pid")) or None
        supervisor_pid = _safe_int(status_payload.get("supervisor_pid")) or None
        daemon_identity = (
            _process_birth_identity(daemon_pid) if daemon_pid is not None else None
        )
        supervisor_identity = (
            _process_birth_identity(supervisor_pid)
            if supervisor_pid is not None
            else None
        )
        daemon_argv = tuple(
            str(item) for item in (daemon_identity or {}).get("argv") or ()
        )
        supervisor_argv = tuple(
            str(item) for item in (supervisor_identity or {}).get("argv") or ()
        )
        lane_rows.append(
            {
                "lane": status_path.parent.name,
                "status_age_seconds": round(
                    max(0.0, now - status_path.stat().st_mtime), 1
                ),
                "heartbeat_age_seconds": _timestamp_age_seconds(
                    state_payload.get("heartbeat_at"), now=now
                ),
                "daemon_pid": daemon_pid,
                "daemon_bound": bool(
                    daemon_identity
                    and "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon"
                    in daemon_argv
                    and _option_value(daemon_argv, "--todo-path")
                    == str(
                        root
                        / "docs/architecture/agent_supervisor_duckdb_quack_control_plane.todo.md"
                    )
                    and _option_value(daemon_argv, "--state-dir")
                    == str(status_path.parent)
                ),
                "supervisor_pid": supervisor_pid,
                "supervisor_bound": bool(
                    supervisor_identity
                    and str(
                        root
                        / "scripts/ops/agent_supervisor/implementation_supervisor_entry.py"
                    )
                    in supervisor_argv
                ),
                "active_worker_count": _safe_int(
                    status_payload.get("active_worker_count")
                ),
                "stalled_without_active_worker": bool(
                    status_payload.get("stalled_without_active_worker")
                ),
                "worker_phase_age_seconds": (
                    float(status_payload["worker_phase_age_seconds"])
                    if isinstance(
                        status_payload.get("worker_phase_age_seconds"),
                        (int, float),
                    )
                    else None
                ),
                "active_task_id": str(state_payload.get("active_task_id") or ""),
                "active_phase": str(state_payload.get("active_phase") or ""),
                "active_phase_age_seconds": _timestamp_age_seconds(
                    state_payload.get("active_phase_started_at"), now=now
                ),
                "active_log_age_seconds": (
                    round(max(0.0, now - active_log_stat.st_mtime), 1)
                    if active_log_stat is not None
                    else None
                ),
                "selection_idle_reason": str(
                    state_payload.get("selection_idle_reason") or ""
                ),
                "progress_token": [
                    str(state_payload.get("active_task_id") or ""),
                    str(state_payload.get("active_phase") or ""),
                    (
                        int(active_log_stat.st_mtime_ns)
                        if active_log_stat is not None
                        else 0
                    ),
                    int(active_log_stat.st_size) if active_log_stat is not None else 0,
                    str(state_payload.get("last_merge_commit") or ""),
                    _safe_int(state_payload.get("completed_count")),
                ],
            }
        )
    stale_lanes: list[str] = []
    for lane in lane_rows:
        worker_active = bool(
            lane["active_task_id"]
            and lane["active_worker_count"] > 0
            and not lane["stalled_without_active_worker"]
        )
        active_overdue = bool(
            worker_active
            and isinstance(lane["active_phase_age_seconds"], (int, float))
            and lane["active_phase_age_seconds"] > 21600
            and (
                not isinstance(lane["active_log_age_seconds"], (int, float))
                or lane["active_log_age_seconds"] > 1800
            )
        )
        if (
            lane["status_age_seconds"] > 1200
            or _lane_task_heartbeat_is_stale(lane, stale_seconds=1200)
            or active_overdue
            or not lane["daemon_bound"]
            or not lane["supervisor_bound"]
        ):
            stale_lanes.append(str(lane["lane"]))
    board_path = (
        root
        / "docs/architecture/agent_supervisor_duckdb_quack_control_plane.todo.md"
    )
    release_status = "unknown"
    completed_count = 0
    task_count = 0
    try:
        board_text = board_path.read_text(encoding="utf-8")
        statuses = re.findall(r"(?m)^- Status:\s*`?([A-Za-z_-]+)`?\s*$", board_text)
        task_count = len(statuses)
        completed_count = sum(
            status.strip().lower() == "completed" for status in statuses
        )
        match = re.search(
            r"(?ms)^## DQP-039\b.*?(?=^## DQP-|\Z)", board_text
        )
        if match:
            status_match = re.search(
                r"(?m)^- Status:\s*`?([A-Za-z_-]+)`?\s*$", match.group(0)
            )
            if status_match:
                release_status = status_match.group(1).lower()
    except OSError:
        pass
    return {
        "program_id": "agent-supervisor-duckdb-quack-control-plane-v1",
        "root": str(root),
        "master_pid": pid,
        "master_alive": master_alive,
        "expected_lane_count": 4,
        "lane_count": len(lane_rows),
        "stale_or_unbound_lanes": stale_lanes,
        "lanes": lane_rows,
        "release_task_id": "DQP-039",
        "release_status": release_status,
        "completed_count": completed_count,
        "task_count": task_count,
        "board_path": str(board_path),
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    source = _source()
    payload = task_status(source)
    findings: list[dict[str, Any]] = []
    try:
        source.validate_integrity()
    except Exception as exc:
        findings.append({"severity": "critical", "kind": "integrity", "detail": str(exc)})
    retry_reset_inspection = payload["retry_reset_inspection"]
    if not retry_reset_inspection["ok"]:
        findings.append(
            {
                "severity": "critical",
                "kind": "retry_reset_recovery_incomplete",
                "detail": retry_reset_inspection["error"]
                or _canonical_json(retry_reset_inspection["incomplete"]),
            }
        )
        for item in retry_reset_inspection["incomplete"]:
            if item.get("blocked_reason") == (
                "retry_permit_expired_after_lifecycle_start"
            ):
                findings.append(
                    {
                        "severity": "critical",
                        "kind": "retry_lifecycle_reauthorization_required",
                        "detail": (
                            f"task={item.get('task_cid') or 'unknown'} "
                            f"phase={item.get('phase')}; "
                            f"{item.get('recovery_action')}"
                        ),
                    }
                )
    if not payload["all_succeeded"] and not payload["master_alive"]:
        if payload["authorization_wait"] and not payload["authorization_evidence_failed"]:
            findings.append(
                {
                    "severity": "info",
                    "kind": "manual_authorization_pending",
                    "detail": (
                        "held descendants await authenticated manual gates: "
                        + ",".join(payload["authorization_incomplete_gate_task_ids"])
                    ),
                }
            )
        else:
            findings.append(
                {
                    "severity": "critical",
                    "kind": "master_dead",
                    "detail": (
                        "non-successful tasks remain; process identity reason="
                        + str(payload["master_identity_reason"])
                    ),
                }
            )
    for lane in payload["lane_status"]:
        if (
            not isinstance(lane.get("age_seconds"), (int, float))
            or float(lane["age_seconds"]) > args.stale_seconds
        ):
            findings.append(
                {
                    "severity": "error",
                    "kind": "lane_supervisor_status_stale",
                    "detail": lane["path"],
                }
            )
        if _lane_task_heartbeat_is_stale(
            lane,
            stale_seconds=args.stale_seconds,
        ):
            findings.append(
                {
                    "severity": "error",
                    "kind": "lane_task_heartbeat_stale",
                    "detail": lane["state_path"],
                }
            )
        if lane.get("active_task_id"):
            phase_age = lane.get("active_phase_age_seconds")
            if isinstance(phase_age, (int, float)) and phase_age > 7500:
                findings.append(
                    {
                        "severity": "error",
                        "kind": "active_phase_exceeded_timeout",
                        "detail": (
                            f"{lane['active_task_id']} phase={lane['active_phase']} "
                            f"age={phase_age}s"
                        ),
                    }
                )
            active_log_age = lane.get("active_log_age_seconds")
            if (
                isinstance(active_log_age, (int, float))
                and active_log_age > 1800
                and (
                    lane.get("stalled_without_active_worker")
                    or _safe_int(lane.get("active_worker_count")) == 0
                )
            ):
                findings.append(
                    {
                        "severity": "error",
                        "kind": "active_task_log_stale_without_worker",
                        "detail": (
                            f"{lane['active_task_id']} log_age={active_log_age}s"
                        ),
                    }
                )
        if payload["master_alive"] and not lane.get("daemon_alive"):
            findings.append(
                {
                    "severity": "error",
                    "kind": "lane_daemon_dead",
                    "detail": lane["path"],
                }
            )
        if not lane.get("source_contract_bound"):
            findings.append(
                {
                    "severity": "error",
                    "kind": "lane_source_contract_mismatch",
                    "detail": lane["path"],
                }
            )
        if lane.get("attempt_limited_task_ids"):
            findings.append(
                {
                    "severity": "error",
                    "kind": "attempt_budget_exhausted",
                    "detail": ", ".join(lane["attempt_limited_task_ids"]),
                }
            )
        if lane.get("attempt_ledger_divergences"):
            findings.append(
                {
                    "severity": "error",
                    "kind": "attempt_ledger_divergence",
                    "detail": _canonical_json(lane["attempt_ledger_divergences"]),
                }
            )
        idle_reason = str(lane.get("selection_idle_reason") or "")
        if "reached_max_task_attempts" in idle_reason:
            findings.append(
                {
                    "severity": "error",
                    "kind": "lane_idle_at_attempt_limit",
                    "detail": idle_reason,
                }
            )
        if lane.get("provider_capacity_signal"):
            findings.append(
                {
                    "severity": "warning",
                    "kind": "provider_capacity_backoff",
                    "detail": lane["path"],
                }
            )
    for status in ("failed", "quarantined", "cancelled", "skipped"):
        count = _safe_int(payload["status_counts"].get(status))
        if count:
            findings.append(
                {
                    "severity": "error",
                    "kind": f"tasks_{status}",
                    "detail": str(count),
                }
            )
    declared_blocked = sum(
        gate["status"] == "blocked" for gate in payload["blocked_gates"]
    )
    unexpected_blocked = max(
        0,
        _safe_int(payload["status_counts"].get("blocked")) - declared_blocked,
    )
    if unexpected_blocked:
        findings.append(
            {
                "severity": "error",
                "kind": "tasks_blocked_unexpected",
                "detail": str(unexpected_blocked),
            }
        )
    for gate in payload["blocked_gates"]:
        if gate["status"] == "blocked":
            findings.append(
                {
                    "severity": "info",
                    "kind": "manual_authorization_pending",
                    "detail": (
                        f"{gate['task_id']}: {gate['reason']}; "
                        f"held_set={payload['authorization_held_set_sha256']}"
                    ),
                }
            )
        elif not gate["authorization_verified"]:
            findings.append(
                {
                    "severity": "critical",
                    "kind": "manual_gate_authentication_failed",
                    "detail": f"{gate['task_id']}: {gate['authorization_detail']}",
                }
            )
    if payload["master_alive"] and not payload["lane_status"]:
        age = max(0.0, time.time() - MASTER_PID.stat().st_mtime) if MASTER_PID.exists() else 0.0
        if age > 420:
            findings.append({"severity": "error", "kind": "no_lane_status", "detail": f"master age={age:.1f}s"})
    if (
        payload["master_alive"]
        and payload["expected_lane_count"]
        and payload["observed_lane_count"] != payload["expected_lane_count"]
    ):
        identity_age = (
            max(0.0, time.time() - MASTER_IDENTITY.stat().st_mtime)
            if MASTER_IDENTITY.is_file()
            else float("inf")
        )
        if identity_age > 420:
            findings.append(
                {
                    "severity": "error",
                    "kind": "lane_population_mismatch",
                    "detail": (
                        f"observed={payload['observed_lane_count']} "
                        f"expected={payload['expected_lane_count']}"
                    ),
                }
            )
    active_lane_tasks = [
        lane["active_task_id"]
        for lane in payload["lane_status"]
        if lane.get("active_task_id")
    ]
    if payload["ready_task_ids"] and not active_lane_tasks and payload["lane_status"]:
        if all(
            (lane.get("heartbeat_age_seconds") or float("inf")) > 120
            for lane in payload["lane_status"]
        ):
            findings.append(
                {
                    "severity": "error",
                    "kind": "ready_work_unclaimed",
                    "detail": ", ".join(payload["ready_task_ids"][:20]),
                }
            )
    external = _external_dqp_status()
    release_gate = next(
        (
            gate
            for gate in payload["blocked_gates"]
            if gate["task_id"] == RELEASE_GATE_TASK_ID
        ),
        None,
    )
    if release_gate and release_gate["status"] != "completed":
        external_unhealthy = (
            not external["master_alive"]
            or external["lane_count"] != external["expected_lane_count"]
            or bool(external["stale_or_unbound_lanes"])
        )
        if external_unhealthy:
            findings.append(
                {
                    "severity": "critical",
                    "kind": "external_dqp_owner_unhealthy",
                    "detail": _canonical_json(external),
                }
            )
        else:
            findings.append(
                {
                    "severity": "info",
                    "kind": "external_dqp_progress",
                    "detail": (
                        f"{external['completed_count']}/{external['task_count']} completed; "
                        f"DQP-039={external['release_status']}"
                    ),
                }
            )
    result = {
        "healthy": not any(
            item["severity"] in {"critical", "error"} for item in findings
        ),
        "status": payload,
        "external_dqp": external,
        "findings": findings,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["healthy"] else 2


def cmd_watch(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout if args.timeout > 0 else None
    last_durable_signature: tuple[Any, ...] | None = None
    last_activity_signature: tuple[Any, ...] | None = None
    last_activity = time.monotonic()
    while True:
        payload = task_status(_source())
        release_gate = next(
            (
                gate
                for gate in payload["blocked_gates"]
                if gate["task_id"] == RELEASE_GATE_TASK_ID
            ),
            None,
        )
        external = (
            _external_dqp_status()
            if release_gate and release_gate["status"] != "completed"
            else None
        )
        external_signature: tuple[Any, ...] = ()
        if external is not None:
            external_signature = (
                external["completed_count"],
                external["release_status"],
                tuple(
                    tuple(lane.get("progress_token") or ())
                    for lane in external["lanes"]
                ),
            )
        durable_signature = (
            payload["revision"],
            tuple(sorted(payload["status_counts"].items())),
        )
        activity_signature = (
            durable_signature,
            payload["master_alive"],
            tuple(
                tuple(lane.get("activity_token") or ())
                for lane in payload["lane_status"]
            ),
            external_signature,
        )
        if activity_signature != last_activity_signature:
            last_activity_signature = activity_signature
            last_activity = time.monotonic()
        if durable_signature != last_durable_signature:
            print(
                f"revision={payload['revision']} terminal={payload['terminal_count']}/{payload['task_count']} "
                f"master={'live' if payload['master_alive'] else 'dead'} statuses={payload['status_counts']}",
                flush=True,
            )
            last_durable_signature = durable_signature
        if payload["drained"]:
            if not payload["all_succeeded"]:
                print(
                    "task graph drained with terminal failures: "
                    + _canonical_json(payload["terminal_failures"]),
                    file=sys.stderr,
                )
                return 6
            if args.stop_master and payload["master_pid"]:
                bound, reason = _master_process_status(
                    int(payload["master_pid"]),
                    expected_plan_root=payload["plan_root_cid"],
                    expected_repository_root=payload["repository_tree_id"],
                )
                if not bound:
                    print(
                        f"refused to signal unbound PID: {reason}",
                        file=sys.stderr,
                    )
                    return 7
                os.kill(int(payload["master_pid"]), signal.SIGTERM)
                print(f"sent SIGTERM to successful master pid={payload['master_pid']}")
            return 0
        if not payload["master_alive"] and not (
            payload["authorization_wait"]
            and not payload["authorization_evidence_failed"]
        ):
            print("master exited while nonterminal tasks remain", file=sys.stderr)
            return 2
        if external is not None and (
            not external["master_alive"]
            or external["lane_count"] != external["expected_lane_count"]
            or external["stale_or_unbound_lanes"]
        ):
            print("external DQP lifecycle owner is unhealthy", file=sys.stderr)
            return 8
        progress_threshold = (
            max(args.no_progress_seconds, 23400.0)
            if external is not None
            else args.no_progress_seconds
        )
        if (
            not (
                payload["authorization_wait"]
                and not payload["authorization_evidence_failed"]
                and external is None
            )
            and time.monotonic() - last_activity > progress_threshold
        ):
            print(
                f"no database, phase, log, or external-release progress for {progress_threshold:.0f}s; run doctor and inspect {MASTER_LOG}",
                file=sys.stderr,
            )
            return 3
        if deadline is not None and time.monotonic() >= deadline:
            print("watch window ended before successful completion", file=sys.stderr)
            return 4
        time.sleep(min(args.interval, 60.0))


def _lane_count(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= MAX_IMPLEMENTATION_LANES:
        raise argparse.ArgumentTypeError(
            f"lanes must be between 1 and the safe cap {MAX_IMPLEMENTATION_LANES}"
        )
    return parsed


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _positive_seconds(value: str) -> float:
    parsed = float(value)
    if not parsed > 0 or parsed == float("inf"):
        raise argparse.ArgumentTypeError("value must be a finite positive number")
    return parsed


def _nonnegative_seconds(value: str) -> float:
    parsed = float(value)
    if not parsed >= 0 or parsed == float("inf"):
        raise argparse.ArgumentTypeError("value must be a finite non-negative number")
    return parsed


def _duration_seconds(value: str) -> float:
    parsed = float(value)
    if not parsed > 0:
        raise argparse.ArgumentTypeError("duration must be positive or 'inf'")
    return parsed


def _no_progress_seconds(value: str) -> float:
    parsed = _positive_seconds(value)
    if parsed < 7500:
        raise argparse.ArgumentTypeError(
            "no-progress threshold must cover the 7200s implementation timeout"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_environment = subparsers.add_parser(
        "bootstrap-environment",
        help="create or verify the dedicated hash-locked DuckDB bootstrap environment",
    )
    bootstrap_environment.set_defaults(handler=cmd_bootstrap_environment)

    bootstrap = subparsers.add_parser("bootstrap", help="materialize the canonical DuckDB plan")
    bootstrap.add_argument("--expected-absent", action="store_true")
    bootstrap.set_defaults(handler=cmd_bootstrap)

    acknowledge = subparsers.add_parser("ack-bootstrap", help="record the already-merged bridge as completed")
    acknowledge.set_defaults(handler=cmd_ack_bootstrap)

    release = subparsers.add_parser(
        "ack-release", help="verify and complete the external DQP release gate"
    )
    release.add_argument("--receipt", type=Path, required=True)
    release.add_argument(
        "--expected-task-revision", type=_positive_integer, required=True
    )
    release.set_defaults(handler=cmd_ack_release)

    refinement = subparsers.add_parser(
        "ack-refinement", help="verify and complete the inventory-refinement gate"
    )
    refinement.add_argument("--receipt", type=Path, required=True)
    refinement.add_argument(
        "--expected-task-revision", type=_positive_integer, required=True
    )
    refinement.set_defaults(handler=cmd_ack_refinement)

    promotion = subparsers.add_parser(
        "ack-promotion",
        help="execute and authenticate the DuckLake authority-promotion gate",
    )
    promotion.add_argument("--receipt", type=Path, required=True)
    promotion.add_argument(
        "--expected-task-revision", type=_positive_integer, required=True
    )
    promotion.set_defaults(handler=cmd_ack_promotion)

    activation = subparsers.add_parser(
        "ack-runtime-activation",
        help="execute and authenticate the DuckDB/Quack/DuckLake runtime gate",
    )
    activation.add_argument("--receipt", type=Path, required=True)
    activation.add_argument(
        "--expected-task-revision", type=_positive_integer, required=True
    )
    activation.set_defaults(handler=cmd_ack_runtime_activation)

    export = subparsers.add_parser("export", help="export a deterministic projection")
    export.add_argument("--format", choices=("markdown", "json"), default="markdown")
    export.add_argument("--output", default=None)
    export.add_argument("--force", action="store_true")
    export.set_defaults(handler=cmd_export)

    preflight = subparsers.add_parser("preflight", help="run safe launch admission checks")
    preflight.add_argument("--allow-dirty", action="store_true")
    preflight.add_argument("--json", action="store_true")
    preflight.set_defaults(handler=cmd_preflight)

    smoke = subparsers.add_parser(
        "smoke", help="run a pure read/parse probe without starting a daemon"
    )
    smoke.add_argument("--dry-run", action="store_true")
    smoke.set_defaults(handler=cmd_smoke)

    launch = subparsers.add_parser("launch", help="launch isolated sharded implementation supervisors")
    launch.add_argument("--lanes", type=_lane_count, default=MAX_IMPLEMENTATION_LANES)
    launch.add_argument("--duration-seconds", type=_duration_seconds, default=float("inf"))
    launch.add_argument("--dry-run", action="store_true")
    launch.add_argument("--foreground", action="store_true")
    launch.set_defaults(handler=cmd_launch)

    retry_preview = subparsers.add_parser(
        "retry-preview",
        help="validate and project a pre-authorized governed task retry",
    )
    retry_preview.add_argument("--request-file", type=Path, required=True)
    retry_preview.set_defaults(handler=cmd_retry_preview)

    recover_task = subparsers.add_parser(
        "recover-task",
        help="drain, reset, and relaunch around an authorized task retry",
    )
    recover_task.add_argument("--request-file", type=Path, required=True)
    recover_task.add_argument(
        "--drain-timeout-seconds",
        type=_positive_seconds,
        default=90.0,
    )
    recover_task.set_defaults(handler=cmd_recover_task)

    status = subparsers.add_parser("status", help="show database and supervisor state")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    doctor = subparsers.add_parser("doctor", help="diagnose stalls and blockers")
    doctor.add_argument("--stale-seconds", type=_positive_seconds, default=900.0)
    doctor.set_defaults(handler=cmd_doctor)

    watch = subparsers.add_parser("watch", help="watch progress without mutating work")
    watch.add_argument("--interval", type=_positive_seconds, default=30.0)
    watch.add_argument("--timeout", type=_nonnegative_seconds, default=0.0)
    watch.add_argument("--no-progress-seconds", type=_no_progress_seconds, default=8100.0)
    watch.add_argument("--stop-master", action="store_true")
    watch.set_defaults(handler=cmd_watch)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
