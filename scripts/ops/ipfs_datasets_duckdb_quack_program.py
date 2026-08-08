#!/usr/bin/env python3
"""Bootstrap, export, launch, and inspect the DuckDB/Quack migration program.

The checked-in Python data below is a reproducible seed migration.  After
``bootstrap`` succeeds, the DuckDB task source is the mutable authority;
Markdown and JSON are deterministic, one-way exports only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


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
DEFAULT_MARKDOWN_EXPORT = (
    REPO_ROOT
    / "docs/architecture/IPFS_DATASETS_DUCKDB_QUACK_CONTROL_PLANE_PLAN.md"
)
PROGRAM_SCHEMA = "ipfs_datasets_py/duckdb-quack-migration-program@1"
PROGRAM_ID = "ipfs-datasets-duckdb-quack-v1"
BOARD_NAMESPACE = "ipfs-datasets-duckdb-quack"
TARGET_BRANCH = "feat/duckdb-quack-control-plane"
ROOT_GOAL_ID = "DQK-G000"
ROOT_GOAL_CID = "goal:cid:dqk-g000"
BOOTSTRAP_TASK_ID = "DQK-007"
REQUIRED_DUCKDB_VERSION = (1, 5, 5)
MINIMUM_QUACK_VERSION = (1, 5, 3)


ARCHITECTURE: dict[str, Any] = {
    "decision": (
        "DuckDB tables become the authority for mutable orchestration, planning, "
        "analysis, lifecycle events, and normalized query projections. Quack is a "
        "replaceable DuckDB-to-DuckDB SQL transport; it is not the scheduler."
    ),
    "principles": [
        "No mutable operational truth in Markdown, JSON, JSONL, YAML, or ad-hoc text files.",
        "Keep versioned executable migrations and seed migrations in Git with checksums.",
        "Make Markdown/JSON deterministic one-way exports bound to a schema, revision, query, and digest.",
        "Keep large immutable bytes in IPLD/CAR/Parquet/object storage and address them by CID from DuckDB.",
        "Separate the small control writer from graph/vector/proof/wallet analytical catalogs.",
        "Use short transactions, compare-and-swap revisions, fenced leases, idempotency keys, and append-only events.",
        "Treat every Quack endpoint as a full-SQL trust boundary and expose allowlisted views or query templates.",
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
        "quack_gateway": (
            "Pinned DuckDB/Quack server processes on loopback by default, with separate endpoint "
            "and OS identities per trust domain; TLS reverse proxy only when remote access is required."
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
    },
    "rollout": [
        "Inventory and classify authored documents, mutable state, immutable evidence, and derived exports.",
        "Install schema registry, checksummed migrations, capability gates, and connection policy.",
        "Import legacy state in bounded idempotent batches while retaining original byte digests and reject rows.",
        "Run DuckDB as a shadow projection and emit differential/parity receipts.",
        "Enable dual writes with a crash-recoverable outbox or journal and quarantine disagreements.",
        "Canary one namespace per domain; prove restore, rollback, and fail-closed behavior.",
        "Promote DuckDB authority only after acceptance gates and make legacy files export-only.",
        "Scan the repository and runtime roots for residual file-authoritative producers before final cutover.",
    ],
    "quack_constraints": [
        "Pin DuckDB and Quack to 1.5.5 initially and repeat compatibility tests before every update.",
        "Quack is beta until DuckDB 2.0; keep a local transport implementation and a feature gate.",
        "Prefer stateless single-statement server-side SQL for mutations; avoid remote ALTER and direct attached UPDATE/DELETE dependencies.",
        "Retry optimistic transaction conflicts with bounded jitter and make every mutation idempotent.",
        "Quack has no server push, task queue, lease manager, replication, failover, or watchdog; the supervisor supplies them.",
        "Use loopback, per-agent credentials, restricted OS identities, disabled external access, and a TLS reverse proxy for remote use.",
    ],
    "success_metrics": [
        "Zero mutable orchestration/planning/analysis/logging authorities remain in Markdown or JSON after cutover.",
        "Every schema and extension change is checksummed, replayable, and covered by compatibility tests.",
        "No duplicate task execution or stale publication after lease expiry, crash, or lost response.",
        "Graph, vector, proof, AST, and wallet predicates can execute in parallel without starving control-plane heartbeats.",
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
        "acceptance_criteria": ["Goals/tasks/events are database authoritative", "Expired or stalled work is recovered without duplicate publication"],
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
    return {
        "task_id": task_id,
        "task_cid": f"task:cid:{task_id.lower()}",
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
        "completion": "code",
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
        "DQK-006", "DQK-G100", "Expose schema, migration, integrity, and snapshot CLI",
        "Add a fail-closed operational CLI for create, migrate, inspect, check, snapshot, and capability status without accepting arbitrary SQL.",
        depends_on=("DQK-003", "DQK-004", "DQK-005"),
        outputs=("ipfs_datasets_py/duckdb_control/cli.py", "tests/cli/test_duckdb_control_cli.py"),
        validations=("python -m pytest -q tests/cli/test_duckdb_control_cli.py",),
        acceptance=("Every mutating command is idempotent and receipted", "Dry-run produces no database change", "CLI output has bounded text and structured modes"),
        track="foundation",
    ),
    _task(
        "DQK-007", "DQK-G200", "Bridge canonical DuckDB task sources through the supervisor",
        "Propagate task-source kind and exact plan/repository roots from the implementation supervisor to its daemon, and fence all Markdown-only repairs away from DuckDB bytes.",
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/todo_daemon/implementation_supervisor.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_implementation_daemon_runner.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_implementation_daemon_runner.py",),
        acceptance=("The managed child command binds DuckDB source kind and both roots", "Invalid UTF-8 DuckDB bytes cannot be read, renamed, or replaced as Markdown", "Legacy Markdown behavior remains compatible"),
        track="supervisor",
        priority="P0",
    ),
    _task(
        "DQK-008", "DQK-G200", "Create the unified supervisor runtime schema",
        "Extend the existing DuckDB task source and lease coordination contracts with workers, attempts, claims, blockers, retry budgets, worktree state, validation results, merge receipts, checkpoints, and typed runtime status.",
        depends_on=("DQK-003", "DQK-004", "DQK-007"),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_runtime_state.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_runtime_state.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_runtime_state.py",),
        acceptance=("Claims are atomic and fenced", "The schema records attempts and blockers without mutable JSON sidecars", "Existing DuckDBTaskSource identities and CAS history remain valid"),
        track="supervisor",
    ),
    _task(
        "DQK-009", "DQK-G200", "Migrate supervisor task state, strategy, queue, and checkpoints",
        "Replace JSON task-state, strategy, persistent queue, continuation, and checkpoint authorities with transactional DuckDB repositories and one-time idempotent import receipts.",
        depends_on=("DQK-008",),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_checkpoint_store.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_checkpoint_store.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_checkpoint_store.py",),
        acceptance=("Invalid legacy JSON cannot silently become empty state", "Imports retain source digests and rejects", "Restart recovers the same queue and strategy revision"),
        track="supervisor",
    ),
    _task(
        "DQK-010", "DQK-G200", "Migrate supervisor events, logs, and scan receipts",
        "Replace authoritative JSONL lifecycle logs and per-scan JSON receipt fanout with typed append-only event and receipt tables while retaining content-addressed large log blobs.",
        depends_on=("DQK-008",),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_event_log.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_event_log.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_event_log.py",),
        acceptance=("Hash-chain/tamper semantics survive", "52,000 scan receipts import in bounded batches", "Event cursor and trace queries do not depend on file mtimes"),
        track="supervisor",
    ),
    _task(
        "DQK-011", "DQK-G200", "Implement Quack-backed canonical task-source transport",
        "Add a transport adapter using stateless server-side SQL for bounded queries and atomic CAS mutations, with root pinning, idempotency, retry/jitter, and local DuckDB parity.",
        depends_on=("DQK-002", "DQK-005", "DQK-007"),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/quack_task_source.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_quack_task_source.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_quack_task_source.py",),
        acceptance=("Lost responses are safe to retry", "Direct attached UPDATE/DELETE and remote ALTER are not required", "Local and Quack task lifecycle traces are equivalent"),
        track="supervisor",
    ),
    _task(
        "DQK-012", "DQK-G200", "Add database-native heartbeats, leases, reaper, and deadlock detection",
        "Unify existing lease coordination with task claims so agents renew independently, stale fences cannot publish, expired claims requeue, cycles/deadlocks are typed, and attempt budgets quarantine terminal work.",
        depends_on=("DQK-008", "DQK-011"),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_lifecycle.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_lifecycle.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_lifecycle.py",),
        acceptance=("A stale worker cannot complete or merge", "Orphan recovery is deterministic", "No-ready-work states distinguish completion, dependency wait, deadlock, capacity, policy, and terminal failure"),
        track="supervisor",
    ),
    _task(
        "DQK-013", "DQK-G200", "Move objective analysis and refill into DuckDB",
        "Replace Markdown objective journals and JSON objective/AST/conflict/dependency artifacts with relational projections and bounded residual-analysis transactions that create versioned subgoals/tasks.",
        depends_on=("DQK-009", "DQK-012"),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_objective_store.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_objective_store.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_objective_store.py",),
        acceptance=("Refill never edits a Markdown board", "New tasks bind objective revision and evidence", "Duplicate findings are idempotently suppressed"),
        track="supervisor",
    ),
    _task(
        "DQK-014", "DQK-G200", "Build supervisor doctor, watchdog, status, and export projections",
        "Make database heartbeats, event cursors, queue age, lease age, attempt age, merge age, provider capacity, disk, and query latency drive monitoring and safe recovery; keep files as temporary human projections only.",
        depends_on=("DQK-010", "DQK-012", "DQK-013"),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_watchdog.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_watchdog.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_watchdog.py",),
        acceptance=("Fresh wrappers cannot hide stale task progress", "Recovery preserves dirty work and receipts", "Terminal completion is evidence-driven, never inferred from process exit"),
        track="supervisor",
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
        depends_on=("DQK-012", "DQK-025"),
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
        "DQK-034", "DQK-G600", "Migrate supervisor analysis artifacts into the shared AST plane",
        "Replace analysis_ast_index, semantic dependency, conflict graph, and code-evidence JSON authorities with transactional projections and deterministic exports.",
        depends_on=("DQK-010", "DQK-013", "DQK-031", "DQK-033"),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_analysis_store.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_analysis_store.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_analysis_store.py",),
        acceptance=("Planning and validation use the same revision-bound projections", "No whole-artifact JSON load is required", "Exports are explicitly non-authoritative"),
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
        "Attach control, graph/vector, proof, AST, and wallet catalogs through explicit read/write roles so expensive scans cannot hold the control writer or starve lease heartbeats.",
        depends_on=("DQK-005", "DQK-008", "DQK-016", "DQK-020", "DQK-025", "DQK-031", "DQK-035"),
        outputs=("ipfs_datasets_py/duckdb_control/federation.py", "tests/integration/test_duckdb_catalog_federation.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_catalog_federation.py",),
        acceptance=("Catalog roles are least privilege", "Cross-catalog snapshots expose revision bindings", "Analytical cancellation leaves control-plane transactions healthy"),
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
        depends_on=("DQK-006", "DQK-041", "DQK-042"),
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
        "Generalize the supervisor dual-task-source journal into domain-neutral authority transitions with crash recovery, differential receipts, disagreement quarantine, and explicit promotion/rollback decisions.",
        depends_on=("DQK-003", "DQK-004", "DQK-044", "DQK-045"),
        outputs=("ipfs_datasets_py/duckdb_control/authority_transition.py", "tests/integration/test_duckdb_authority_transition.py"),
        validations=("python -m pytest -q tests/integration/test_duckdb_authority_transition.py",),
        acceptance=("Crash at every dual-write boundary recovers", "Mismatch never silently promotes", "Promotion and rollback are idempotent, fenced, and receipted"),
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
        depends_on=("DQK-010", "DQK-044", "DQK-047"),
        outputs=("benchmarks/duckdb_quack_migration_benchmark.py", "tests/benchmarks/test_duckdb_quack_migration_benchmark.py"),
        validations=("python -m pytest -q tests/benchmarks/test_duckdb_quack_migration_benchmark.py",),
        acceptance=("Benchmark is resumable and does not mutate the fixture", "Peak memory and transaction latency stay within declared budgets", "Every migrated population has count and digest parity receipts"),
        track="migration",
        priority="P2",
    ),
    _task(
        "DQK-049", "DQK-G1000", "Harden Quack authentication, authorization, TLS, and process isolation",
        "Create a Quack threat model and guarded server launcher using loopback defaults, per-agent credentials, DuckDB secrets, restricted OS identity, disabled external access, query authorization, audit, and a supported TLS reverse-proxy profile.",
        depends_on=("DQK-002", "DQK-005", "DQK-011", "DQK-041"),
        outputs=("ipfs_datasets_py/duckdb_control/quack_security.py", "tests/security/test_quack_security.py"),
        validations=("python -m pytest -q tests/security/test_quack_security.py",),
        acceptance=("Default authorization is never permissive for agent traffic", "Remote plaintext exposure is rejected", "Tokens and full SQL text are handled as sensitive"),
        track="security",
    ),
    _task(
        "DQK-050", "DQK-G1000", "Create Quack protocol and upgrade compatibility suite",
        "Test local/stateless/attached sessions, transactions, large fetches, known attached UPDATE/DELETE and ALTER gaps, rollback behavior, crashed-client resource cleanup, authentication hooks, extension pinning, and upgrade refusal.",
        depends_on=("DQK-002", "DQK-011", "DQK-049"),
        outputs=("tests/compatibility/test_duckdb_quack_contract.py", "scripts/validation/validate_duckdb_quack_compatibility.py"),
        validations=("python -m pytest -q tests/compatibility/test_duckdb_quack_contract.py",),
        acceptance=("Known gaps have tested workarounds or hard gates", "Server/client mismatch fails before mutation", "DuckDB 2.0 adoption requires an explicit requalification receipt"),
        track="security",
    ),
    _task(
        "DQK-051", "DQK-G1000", "Add concurrency, crash, corruption, and stall chaos tests",
        "Inject failures at claim, heartbeat, proof publication, graph/vector/wallet batch, checkpoint, export, merge, backup, Quack response, and process death boundaries; prove bounded recovery and no duplicate authority.",
        depends_on=("DQK-012", "DQK-027", "DQK-042", "DQK-046", "DQK-047", "DQK-050"),
        outputs=("tests/chaos/test_duckdb_quack_control_plane.py", "scripts/validation/validate_duckdb_quack_chaos.py"),
        validations=("python -m pytest -q tests/chaos/test_duckdb_quack_control_plane.py",),
        acceptance=("Stale fences cannot publish", "No-progress and deadlock diagnoses are typed", "Recovery preserves dirty work and immutable evidence"),
        track="security",
    ),
    _task(
        "DQK-052", "DQK-G1000", "Unify observability, audit, traces, and query profiles",
        "Store lifecycle events, trace/span correlation, health samples, query profiles, blocker transitions, dead letters, and audit records in a typed append-only observability catalog with bounded retention/export.",
        depends_on=("DQK-010", "DQK-014", "DQK-041"),
        outputs=("ipfs_datasets_py/duckdb_control/observability.py", "tests/unit/duckdb_control/test_observability.py"),
        validations=("python -m pytest -q tests/unit/duckdb_control/test_observability.py",),
        acceptance=("File mtimes are not progress authority", "Sensitive query text is redacted/classified", "Control, query, proof, graph, vector, AST, and wallet traces correlate by IDs"),
        track="security",
    ),
    _task(
        "DQK-053", "DQK-G1100", "Run domain canaries and prove cutover/rollback gates",
        "Canary the supervisor, proof, graph/vector, AST, and wallet namespaces in dependency order using shadow/dual authority, SLO/parity/security/restore evidence, and an explicit rollback window.",
        depends_on=("DQK-014", "DQK-024", "DQK-030", "DQK-034", "DQK-039", "DQK-046", "DQK-047", "DQK-051", "DQK-052"),
        outputs=("scripts/ops/duckdb_quack_canary.py", "tests/e2e/test_duckdb_quack_canary.py"),
        validations=("python -m pytest -q tests/e2e/test_duckdb_quack_canary.py",),
        acceptance=("Each authority promotion has evidence and a tested rollback", "Canary failures quarantine only their namespace", "Legacy producers become export-only after promotion"),
        track="rollout",
    ),
    _task(
        "DQK-054", "DQK-G1100", "Implement database-native residual analysis and self-improvement",
        "Run bounded inventory, schema, parity, performance, blocker, and coverage analyzers against identified snapshots; admit deduplicated findings as revision-bound subgoals/tasks with evidence and budgets.",
        depends_on=("DQK-013", "DQK-042", "DQK-048", "DQK-052", "DQK-053"),
        outputs=("ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/duckdb_self_improvement.py", "ipfs_accelerate_py/test/api/test_agent_supervisor_duckdb_self_improvement.py"),
        validations=("cd ipfs_accelerate_py && python -m pytest -q test/api/test_agent_supervisor_duckdb_self_improvement.py",),
        acceptance=("Findings cannot bypass planning/acceptance policy", "Duplicate or stale findings do not create task storms", "The loop uses DuckDB authority rather than Markdown objective refill"),
        track="rollout",
    ),
    _task(
        "DQK-055", "DQK-G1100", "Complete cutover and scan for residual file authorities",
        "Execute the final producer/consumer scan, prove every mutable file artifact is removed or a declared projection, freeze migration receipts, verify restore/security/performance gates, and publish deterministic release exports.",
        depends_on=("DQK-043", "DQK-045", "DQK-048", "DQK-050", "DQK-051", "DQK-053", "DQK-054"),
        outputs=("scripts/validation/validate_duckdb_quack_cutover.py", "tests/e2e/test_duckdb_quack_cutover.py"),
        validations=("python -m pytest -q tests/e2e/test_duckdb_quack_cutover.py",),
        acceptance=("Zero undeclared mutable Markdown/JSON/JSONL authorities remain", "All domain snapshots and receipts verify", "Quack remains replaceable and upgrade-gated", "Final Markdown/JSON artifacts are reproducible exports only"),
        track="rollout",
        priority="P0",
    ),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    return f"tree:git:{_git('rev-parse', 'HEAD')}"


def _repository_binding_is_ancestor(repository_tree_id: str) -> bool:
    prefix = "tree:git:"
    if not repository_tree_id.startswith(prefix):
        return False
    commit = repository_tree_id[len(prefix) :]
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


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
    output_owner: dict[str, str] = {}
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
            path = str(effect["path"])
            previous = output_owner.get(path)
            if previous is not None:
                raise ValueError(f"output {path!r} is shared by {previous} and {task_id}")
            output_owner[path] = task_id

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


def formal_source(repository_tree_id: str) -> dict[str, Any]:
    validate_program()
    objectives = [dict(goal) for goal in GOALS]
    taskboard: list[dict[str, Any]] = []
    for task in TASKS:
        record = dict(task)
        record["goal_cid"] = _goal_cid(str(record["goal_id"]))
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
    selected = str(ACCELERATE_ROOT)
    if selected not in sys.path:
        sys.path.insert(0, selected)
    from ipfs_accelerate_py.agent_supervisor.duckdb_task_source import DuckDBTaskSource
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
        _goose_meta_spark_available,
        _grok_cli_available,
    )

    return DuckDBTaskSource, (_grok_cli_available, _goose_meta_spark_available)


def _source(*, require: bool = True) -> Any | None:
    DuckDBTaskSource, _providers = _accelerate_imports()
    if not DATABASE_PATH.is_file():
        if require:
            raise RuntimeError(f"control database does not exist: {DATABASE_PATH}")
        return None
    return DuckDBTaskSource(DATABASE_PATH)


def _all_rows(source: Any, table: str) -> list[dict[str, Any]]:
    return [dict(item) for item in source.query(table, cursor=0, limit=1000)]


def _decode_body(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("body_json")
    decoded = json.loads(str(value)) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("task/goal body is not an object")
    return decoded


def database_projection(source: Any) -> dict[str, Any]:
    snapshot = source.snapshot()
    tables = {
        table: _all_rows(source, table)
        for table in (
            "goals",
            "tasks",
            "task_dependencies",
            "task_outputs",
            "task_validations",
            "task_acceptance",
            "task_events",
            "materialization_receipts",
        )
    }
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
        "tables": tables,
    }
    payload["export_digest"] = f"sha256:{_sha256_text(_canonical_json(payload))}"
    return payload


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
        "# IPFS Datasets DuckDB + Quack Control-Plane Improvement Plan",
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
        "    A[Agents and services] -->|allowlisted SQL RPC| Q[Quack gateways]",
        "    Q --> C[(Control DuckDB)]",
        "    Q --> G[(Graph + vector catalog)]",
        "    Q --> P[(Proof catalog)]",
        "    Q --> S[(AST catalog)]",
        "    Q --> W[(Public wallet catalog)]",
        "    G --> I[(IPLD / CAR / Parquet)]",
        "    P --> I",
        "    S --> I",
        "    W --> E[(Encrypted/raw object store)]",
        "    C --> X[Deterministic MD/JSON exports]",
        "```",
        "",
        "The small control writer is isolated from analytical scans. Cross-domain reads attach identified, mostly read-only catalogs; cross-database changes use outboxes, immutable receipts, and idempotent reconciliation instead of assuming atomicity across files.",
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
        outputs = [str(item["path"]) for item in task.get("effects") or ()]
        lines.extend(
            [
                f"### {task['task_id']}: {task['title']}",
                "",
                f"- Status/revision: `{task['status']}` / `{task['revision']}`",
                f"- Goal: `{task['goal_id']}`; priority: `{task['priority']}`; track: `{task['track']}`",
                "- Depends on: " + (", ".join(f"`{item}`" for item in task["depends_on"]) or "none"),
                "- Outputs: " + ", ".join(f"`{item}`" for item in outputs),
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
            "- Quack security: https://duckdb.org/docs/current/quack/security",
            "- DuckDB concurrency: https://duckdb.org/docs/current/connect/concurrency",
            "- DuckDB VSS: https://duckdb.org/docs/lts/core_extensions/vss",
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


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def task_status(source: Any) -> dict[str, Any]:
    snapshot = source.snapshot()
    tasks = _all_rows(source, "tasks")
    counts = Counter(str(row["status"]) for row in tasks)
    terminal_statuses = {"completed", "cancelled", "skipped", "failed", "quarantined"}
    terminal = sum(value for key, value in counts.items() if key in terminal_statuses)
    master_pid = _read_pid(MASTER_PID)
    lanes: list[dict[str, Any]] = []
    now = time.time()
    if STATE_ROOT.is_dir():
        for status_path in sorted(STATE_ROOT.glob("lane-*/*_supervisor_status.json")):
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {"error": "unreadable"}
            lanes.append(
                {
                    "path": str(status_path),
                    "age_seconds": round(max(0.0, now - status_path.stat().st_mtime), 1),
                    "payload": payload,
                }
            )
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
        "all_terminal": terminal == len(tasks),
        "status_counts": dict(sorted(counts.items())),
        "master_pid": master_pid,
        "master_alive": _pid_alive(master_pid),
        "master_log": str(MASTER_LOG),
        "lane_status": lanes,
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

    try:
        import duckdb

        version = str(duckdb.__version__)
        parsed = _version_tuple(version)
        add("duckdb_local_task_source", parsed >= (1, 3, 2), f"installed={version}; minimum local=1.3.2")
        add(
            "quack_runtime",
            parsed >= MINIMUM_QUACK_VERSION,
            f"installed={version}; Quack requires >=1.5.3 and program pin is 1.5.5",
            required=False,
        )
        add(
            "duckdb_program_pin",
            parsed >= REQUIRED_DUCKDB_VERSION,
            f"installed={version}; target={'.'.join(map(str, REQUIRED_DUCKDB_VERSION))}",
            required=False,
        )
    except Exception as exc:
        add("duckdb_local_task_source", False, f"{type(exc).__name__}: {exc}")

    source = _source(require=False)
    if source is None:
        add("control_database", False, f"missing {DATABASE_PATH}")
    else:
        try:
            integrity = source.validate_integrity()
            snapshot = source.snapshot()
            add("control_database", bool(integrity.valid), f"revision={snapshot.revision}; projection={snapshot.projection_cid}")
            add(
                "repository_root_binding",
                _repository_binding_is_ancestor(snapshot.repository_tree_id),
                f"admitted={snapshot.repository_tree_id}; checkout={_repository_tree_id()}; relationship=ancestor-required",
            )
            bootstrap = next(
                row for row in _all_rows(source, "tasks") if row["task_alias"] == BOOTSTRAP_TASK_ID
            )
            add(
                "bootstrap_bridge_receipt",
                str(bootstrap["status"]) == "completed",
                f"{BOOTSTRAP_TASK_ID} status={bootstrap['status']}",
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
    add(
        "runtime_namespace_free",
        not _pid_alive(master_pid),
        "free" if not _pid_alive(master_pid) else f"existing live master pid={master_pid}",
    )
    return checks


def _print_checks(checks: Sequence[Mapping[str, Any]]) -> None:
    for check in checks:
        label = "PASS" if check["ok"] else ("WARN" if not check["required"] else "FAIL")
        print(f"{label:4} {check['name']}: {check['detail']}")


def cmd_bootstrap(args: argparse.Namespace) -> int:
    DuckDBTaskSource, _providers = _accelerate_imports()
    repository_tree = _repository_tree_id()
    source = DuckDBTaskSource(DATABASE_PATH)
    receipt = source.materialize(
        formal_source(repository_tree),
        repository_tree_id=repository_tree,
        expected_absent=bool(args.expected_absent),
        writer_id="bootstrap",
        fencing_token=1,
    )
    integrity = source.validate_integrity()
    print(_canonical_json({"receipt": dict(receipt), "integrity": integrity.valid, "database": str(DATABASE_PATH)}))
    return 0


def cmd_ack_bootstrap(args: argparse.Namespace) -> int:
    source = _source()
    task = source.get_task(BOOTSTRAP_TASK_ID)
    if task is None:
        raise RuntimeError(f"missing bootstrap task {BOOTSTRAP_TASK_ID}")
    if task.status == "completed":
        print(f"{BOOTSTRAP_TASK_ID} is already completed")
        return 0
    if task.status not in {"pending", "ready", "admitted", "proposed"}:
        raise RuntimeError(f"cannot acknowledge {BOOTSTRAP_TASK_ID} from status {task.status}")
    receipt = {
        "kind": "bootstrap_implementation_receipt",
        "superproject_commit": _git("rev-parse", "HEAD"),
        "submodule_commit": _git("-C", "ipfs_accelerate_py", "rev-parse", "HEAD"),
        "validation": list(args.validation),
    }
    result = source.compare_and_set_status(
        BOOTSTRAP_TASK_ID,
        expected_revision=task.revision,
        status="completed",
        receipt=receipt,
    )
    print(_canonical_json({"task": result.task.task_id, "status": result.task.status, "receipt_cid": result.receipt_cid}))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    source = _source()
    if args.format == "markdown":
        rendered = render_markdown(source)
    else:
        rendered = json.dumps(database_projection(source), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output == "-":
        sys.stdout.write(rendered)
        return 0
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.format} export to {output_path}")
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


def cmd_smoke(args: argparse.Namespace) -> int:
    source = _source()
    plan_root, repository_root = _task_source_roots(source)
    smoke_root = RUNTIME_ROOT / "smoke"
    command = [
        sys.executable,
        "-m",
        "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon",
        "--once",
        "--todo-path",
        str(DATABASE_PATH),
        "--task-source-kind",
        "duckdb",
        "--expected-task-source-root",
        plan_root,
        "--expected-task-source-repository-root",
        repository_root,
        "--state-dir",
        str(smoke_root),
        "--state-prefix",
        "dqk_smoke",
        "--task-prefix",
        "DQK-",
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ACCELERATE_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    if args.dry_run:
        print(shlex.join(command))
        return 0
    result = subprocess.run(command, cwd=REPO_ROOT, env=environment, check=False, timeout=args.timeout)
    return int(result.returncode)


def supervisor_command(*, lanes: int, duration_seconds: int, detach: bool) -> list[str]:
    source = _source()
    plan_root, repository_root = _task_source_roots(source)
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
        "--implementation-protected-path",
        str(Path(__file__).resolve().relative_to(REPO_ROOT)),
        "--implementation-protected-path",
        str(DEFAULT_MARKDOWN_EXPORT.relative_to(REPO_ROOT)),
        "--no-retry-budget-guardrail",
        "--no-dependency-guardrail",
        "--no-reconciliation-guardrail",
        "--no-objective-task-janitor",
        "--no-objective-goal-completion-reconcile",
        "--no-objective-goal-migration",
    ]
    stamp = f"dqk-{plan_root.rsplit(':', 1)[-1][:12]}"
    command = [
        sys.executable,
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
        sys.executable,
        "--implementation-track",
        state_spec,
        "--implementation-supervisor-lanes-per-track",
        str(max(1, lanes)),
    ]
    command.extend(f"--common-arg={item}" for item in common_args)
    if detach:
        command.append("--detach")
    return command


def cmd_launch(args: argparse.Namespace) -> int:
    checks = preflight_checks(require_clean=True)
    _print_checks(checks)
    failures = [check for check in checks if check["required"] and not check["ok"]]
    if failures:
        print("launch refused: required preflight checks failed", file=sys.stderr)
        return 2
    command = supervisor_command(
        lanes=args.lanes,
        duration_seconds=args.duration_seconds,
        detach=not args.foreground,
    )
    print("launch command:", shlex.join(command))
    if args.dry_run:
        return 0
    MASTER_ROOT.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ACCELERATE_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    environment.setdefault("IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER", "auto")
    result = subprocess.run(command, cwd=REPO_ROOT, env=environment, check=False)
    if result.returncode:
        return int(result.returncode)
    time.sleep(2)
    payload = task_status(_source())
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not args.foreground and not payload["master_alive"]:
        print("detached master did not remain alive", file=sys.stderr)
        return 3
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
        lane_payload = lane["payload"] if isinstance(lane["payload"], Mapping) else {}
        print(
            f"lane={Path(lane['path']).parent.name} age={lane['age_seconds']}s "
            f"status={lane_payload.get('status') or lane_payload.get('state') or 'unknown'}"
        )
    print(f"master_log={payload['master_log']}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    source = _source()
    payload = task_status(source)
    findings: list[dict[str, Any]] = []
    try:
        source.validate_integrity()
    except Exception as exc:
        findings.append({"severity": "critical", "kind": "integrity", "detail": str(exc)})
    if not payload["all_terminal"] and not payload["master_alive"]:
        findings.append({"severity": "critical", "kind": "master_dead", "detail": "nonterminal tasks remain"})
    for lane in payload["lane_status"]:
        if float(lane["age_seconds"]) > args.stale_seconds:
            findings.append({"severity": "error", "kind": "lane_status_stale", "detail": lane["path"]})
    for status in ("failed", "quarantined", "blocked"):
        count = int(payload["status_counts"].get(status, 0))
        if count:
            findings.append({"severity": "error", "kind": f"tasks_{status}", "detail": str(count)})
    if payload["master_alive"] and not payload["lane_status"]:
        age = max(0.0, time.time() - MASTER_PID.stat().st_mtime) if MASTER_PID.exists() else 0.0
        if age > 420:
            findings.append({"severity": "error", "kind": "no_lane_status", "detail": f"master age={age:.1f}s"})
    result = {"healthy": not any(item["severity"] in {"critical", "error"} for item in findings), "status": payload, "findings": findings}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["healthy"] else 2


def cmd_watch(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout if args.timeout > 0 else None
    last_signature: tuple[Any, ...] | None = None
    last_change = time.monotonic()
    while True:
        payload = task_status(_source())
        signature = (
            payload["revision"],
            tuple(sorted(payload["status_counts"].items())),
            payload["master_alive"],
        )
        if signature != last_signature:
            print(
                f"revision={payload['revision']} terminal={payload['terminal_count']}/{payload['task_count']} "
                f"master={'live' if payload['master_alive'] else 'dead'} statuses={payload['status_counts']}",
                flush=True,
            )
            last_signature = signature
            last_change = time.monotonic()
        if payload["all_terminal"]:
            if args.stop_master and payload["master_alive"] and payload["master_pid"]:
                os.kill(int(payload["master_pid"]), signal.SIGTERM)
                print(f"sent SIGTERM to terminal master pid={payload['master_pid']}")
            return 0
        if not payload["master_alive"]:
            print("master exited while nonterminal tasks remain", file=sys.stderr)
            return 2
        if time.monotonic() - last_change > args.no_progress_seconds:
            print(
                f"no database revision/status progress for {args.no_progress_seconds:.0f}s; run doctor and inspect {MASTER_LOG}",
                file=sys.stderr,
            )
            return 3
        if deadline is not None and time.monotonic() >= deadline:
            return 0
        time.sleep(min(args.interval, 60.0))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="materialize the canonical DuckDB plan")
    bootstrap.add_argument("--expected-absent", action="store_true")
    bootstrap.set_defaults(handler=cmd_bootstrap)

    acknowledge = subparsers.add_parser("ack-bootstrap", help="record the already-merged bridge as completed")
    acknowledge.add_argument("--validation", action="append", default=[])
    acknowledge.set_defaults(handler=cmd_ack_bootstrap)

    export = subparsers.add_parser("export", help="export a deterministic projection")
    export.add_argument("--format", choices=("markdown", "json"), default="markdown")
    export.add_argument("--output", default=str(DEFAULT_MARKDOWN_EXPORT))
    export.set_defaults(handler=cmd_export)

    preflight = subparsers.add_parser("preflight", help="run safe launch admission checks")
    preflight.add_argument("--allow-dirty", action="store_true")
    preflight.add_argument("--json", action="store_true")
    preflight.set_defaults(handler=cmd_preflight)

    smoke = subparsers.add_parser("smoke", help="run one non-implementing daemon pass")
    smoke.add_argument("--dry-run", action="store_true")
    smoke.add_argument("--timeout", type=float, default=180.0)
    smoke.set_defaults(handler=cmd_smoke)

    launch = subparsers.add_parser("launch", help="launch isolated sharded implementation supervisors")
    launch.add_argument("--lanes", type=int, default=2)
    launch.add_argument("--duration-seconds", type=int, default=604800)
    launch.add_argument("--dry-run", action="store_true")
    launch.add_argument("--foreground", action="store_true")
    launch.set_defaults(handler=cmd_launch)

    status = subparsers.add_parser("status", help="show database and supervisor state")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    doctor = subparsers.add_parser("doctor", help="diagnose stalls and blockers")
    doctor.add_argument("--stale-seconds", type=float, default=600.0)
    doctor.set_defaults(handler=cmd_doctor)

    watch = subparsers.add_parser("watch", help="watch progress without mutating work")
    watch.add_argument("--interval", type=float, default=30.0)
    watch.add_argument("--timeout", type=float, default=300.0)
    watch.add_argument("--no-progress-seconds", type=float, default=2400.0)
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
