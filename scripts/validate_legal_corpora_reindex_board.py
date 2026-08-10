#!/usr/bin/env python3
"""Validate the sealed, refill-aware legal-corpora supervisor control plane."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

TASK_PREFIX = "LCR-"
GOAL_PREFIX = "LCR-G"
BOARD_NAMESPACE = "legal-corpora-reindex-v1"
TARGET_DATASETS = {
    "justicedao/ipfs_state_laws": "42f0546acc7c6cd55627eaf51fb820d5613b9021",
    "justicedao/ipfs_federal_register": "720668ae016cc400916dda884c9005e03618edfa",
}
CONFIG_RELATIVE = "config/agent_supervisor_legal_corpora_reindex_scheduler.json"
PLAN_RELATIVE = "docs/architecture/LEGAL_CORPORA_REINDEX_PLAN.md"
OBJECTIVES_RELATIVE = "docs/architecture/legal_corpora_reindex.objectives.md"
TASKBOARD_RELATIVE = "docs/architecture/legal_corpora_reindex.todo.md"
VALIDATOR_RELATIVE = "scripts/validate_legal_corpora_reindex_board.py"
LANE_MATRIX_RELATIVE = "data/agent_supervisor/legal_corpora_reindex/bundles/lane_matrix.json"
RELEASE_POLICY_RELATIVE = "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"

SEALED_TASK_IDS = tuple(f"{TASK_PREFIX}{number:03d}" for number in range(70))
SEALED_GOAL_IDS = (
    "LCR-G000",
    "LCR-G010",
    "LCR-G020",
    "LCR-G021",
    "LCR-G022",
    "LCR-G023",
    "LCR-G024",
    "LCR-G030",
    "LCR-G040",
    "LCR-G050",
    "LCR-G060",
    "LCR-G070",
    "LCR-G080",
    "LCR-G090",
    "LCR-G100",
    "LCR-G110",
    "LCR-G120",
    "LCR-G130",
    "LCR-G140",
)
SEALED_INITIAL_COMPLETED = ("LCR-000",)
SEALED_INITIAL_READY = tuple(
    [f"LCR-{number:03d}" for number in range(1, 9)]
    + [f"LCR-{number:03d}" for number in range(48, 52)]
)

TASK_FIELDS = frozenset(
    {
        "status",
        "completion",
        "is_schedulable",
        "review_only",
        "priority",
        "track",
        "depends_on",
        "goal_id",
        "outputs",
        "validation",
        "board_namespace",
        "bundle",
        "parallel_lane",
        "resource_class",
        "token_class",
        "estimated_tokens",
        "predicted_files",
        "allow_concurrent_with",
        "conflict_policy",
        "preconditions",
        "effects",
        "acceptance",
        "generated_by",
    }
)
GENERATED_TASK_FIELDS = frozenset(
    {
        "status",
        "completion",
        "priority",
        "track",
        "depends_on",
        "goal_id",
        "outputs",
        "validation",
        "board_namespace",
        "acceptance",
    }
)
GOAL_FIELDS = frozenset(
    {
        "status",
        "parent",
        "depends_on",
        "fib_priority",
        "track",
        "priority",
        "bundle",
        "goal",
        "evidence",
        "outputs",
        "validation",
        "acceptance",
        "gap_task",
        "refinement",
        "embedding_query",
        "ast_query",
        "parallel_lane",
        "conflict_policy",
    }
)
GENERATED_GOAL_FIELDS = frozenset(
    {
        "status",
        "parent",
        "fib_priority",
        "track",
        "priority",
        "bundle",
        "goal",
        "evidence",
        "outputs",
        "validation",
        "acceptance",
        "gap_task",
        "embedding_query",
        "ast_query",
        "parallel_lane",
        "conflict_policy",
    }
)

TASK_STATUS_VALUES = frozenset({"todo", "in_progress", "completed", "blocked"})
GOAL_STATUS_VALUES = frozenset(
    {
        "active",
        "provisionally_complete",
        "verified_complete",
        "analysis_inconclusive",
        "blocked",
        "reopened",
    }
)
COMPLETION_VALUES = frozenset({"evidence", "manual", "artifact"})


def _task_contract(
    title: str,
    goal_id: str,
    dependencies: str = "",
) -> tuple[str, str, tuple[str, ...]]:
    return title, goal_id, tuple(
        item.strip() for item in dependencies.split(",") if item.strip()
    )


SEALED_TASK_CONTRACTS = {
    "LCR-000": _task_contract("Seal the initial supervisor control plane", "LCR-G010"),
    "LCR-001": _task_contract("Freeze the live Hugging Face and local baseline", "LCR-G010", "LCR-000"),
    "LCR-002": _task_contract("Catalog authoritative sources for the exact 51-jurisdiction set", "LCR-G010", "LCR-000"),
    "LCR-003": _task_contract("Define the full-scrape completion and admission oracle", "LCR-G010", "LCR-000"),
    "LCR-004": _task_contract("Specify the state-law v2 schema and identity-bound release contract", "LCR-G010", "LCR-000"),
    "LCR-005": _task_contract("Implement frontier-closure and no-truncation audits", "LCR-G010", "LCR-000"),
    "LCR-006": _task_contract("Implement canonical jurisdiction and statute identity", "LCR-G010", "LCR-000"),
    "LCR-007": _task_contract("Build a resumable isolated cohort runner and certifier", "LCR-G010", "LCR-000"),
    "LCR-008": _task_contract("Bind additive Hugging Face publication and credential safety", "LCR-G010", "LCR-000"),
    "LCR-009": _task_contract("Certify full official-source scrape cohort A (AL, AK, AZ, AR)", "LCR-G021", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-010": _task_contract("Certify full official-source scrape cohort B (CA, CO, CT, DE)", "LCR-G021", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-011": _task_contract("Certify full official-source scrape cohort C (FL, GA, HI, ID)", "LCR-G021", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-012": _task_contract("Certify full official-source scrape cohort D (IL, IN, IA, KS)", "LCR-G021", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-013": _task_contract("Certify full official-source scrape cohort E (KY, LA, ME, MD)", "LCR-G022", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-014": _task_contract("Certify full official-source scrape cohort F (MA, MI, MN, MS)", "LCR-G022", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-015": _task_contract("Certify full official-source scrape cohort G (MO, MT, NE, NV)", "LCR-G022", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-016": _task_contract("Certify full official-source scrape cohort H (NH, NJ, NM, NY)", "LCR-G022", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-017": _task_contract("Certify full official-source scrape cohort I (NC, ND, OH, OK)", "LCR-G023", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-018": _task_contract("Certify full official-source scrape cohort J (OR, PA, RI, SC)", "LCR-G023", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-019": _task_contract("Certify full official-source scrape cohort K (SD, TN, TX, UT)", "LCR-G023", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-020": _task_contract("Certify full official-source scrape cohort L (VT, VA, WA, WV)", "LCR-G023", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-021": _task_contract("Certify full official-source scrape cohort M (WI, WY, DC)", "LCR-G023", "LCR-002, LCR-003, LCR-005, LCR-007, LCR-008"),
    "LCR-022": _task_contract("Aggregate all cohort receipts into the exact 51-jurisdiction coverage matrix", "LCR-G024", ", ".join(f"LCR-{number:03d}" for number in range(9, 22))),
    "LCR-023": _task_contract("Refill and close every acquisition evidence gap", "LCR-G024", "LCR-022"),
    "LCR-024": _task_contract("Materialize the canonical corpus and recovery quarantine", "LCR-G030", "LCR-004, LCR-006, LCR-023"),
    "LCR-025": _task_contract("Implement structure-aware state statute chunking", "LCR-G030", "LCR-006, LCR-024"),
    "LCR-026": _task_contract("Adapt the shared bounded Hub GraphRAG substrate to state laws", "LCR-G030", "LCR-004, LCR-024"),
    "LCR-027": _task_contract("Build and prove term-range field-weighted BM25", "LCR-G040", "LCR-025, LCR-026"),
    "LCR-028": _task_contract("Regenerate every embedding in one pinned legal vector space", "LCR-G040", "LCR-025, LCR-026"),
    "LCR-029": _task_contract("Cluster and package deterministic centroid-routed vectors", "LCR-G040", "LCR-026, LCR-028"),
    "LCR-030": _task_contract("Project the multi-jurisdiction legal and provenance graph", "LCR-G040", "LCR-024, LCR-026"),
    "LCR-031": _task_contract("Build bounded two-way adjacency and the postings-backed lexical overlay", "LCR-G040", "LCR-026, LCR-027, LCR-030"),
    "LCR-032": _task_contract("Assemble the descriptor-complete additive release and Viewer configs", "LCR-G040", "LCR-027, LCR-029, LCR-031"),
    "LCR-033": _task_contract("Implement the bounded immutable-Hub state-law query engine", "LCR-G050", "LCR-032"),
    "LCR-034": _task_contract("Expose direct state-law query CLI and package API", "LCR-G050", "LCR-033"),
    "LCR-035": _task_contract("Seal a jurisdiction-diverse retrieval and graph gold set", "LCR-G060", "LCR-023, LCR-024"),
    "LCR-036": _task_contract("Evaluate BM25, vector, hybrid, graph, coverage, and sparse I/O", "LCR-G060", "LCR-027, LCR-029, LCR-031, LCR-034, LCR-035"),
    "LCR-037": _task_contract("Prove deterministic streaming builds and security/resource fail-closed behavior", "LCR-G060", "LCR-026, LCR-032, LCR-033"),
    "LCR-038": _task_contract("Run the complete 51-jurisdiction local build end to end", "LCR-G060", "LCR-023, LCR-032, LCR-034, LCR-036, LCR-037"),
    "LCR-039": _task_contract("Produce the exact release candidate and publication evidence root", "LCR-G070", "LCR-038"),
    "LCR-040": _task_contract("Upload the candidate additively to an explicit staging revision", "LCR-G070", "LCR-008, LCR-039, LCR-070, LCR-074"),
    "LCR-041": _task_contract("Redownload and canary the immutable live staging revision", "LCR-G070", "LCR-040"),
    "LCR-042": _task_contract("Authorize and execute the additive public Hugging Face upload", "LCR-G080", "LCR-008, LCR-041, LCR-072, LCR-074"),
    "LCR-043": _task_contract("Verify the immutable public revision and Dataset Viewer end to end", "LCR-G080", "LCR-042"),
    "LCR-044": _task_contract("Benchmark sparse production queries at the public pin", "LCR-G080", "LCR-036, LCR-043"),
    "LCR-045": _task_contract("Preserve legacy compatibility and rehearse rollback/operations", "LCR-G090", "LCR-043"),
    "LCR-046": _task_contract("Audit post-publication completeness and update readiness", "LCR-G090", "LCR-043, LCR-044, LCR-045"),
    "LCR-047": _task_contract("Seal the state-law public release evidence", "LCR-G090", "LCR-046"),
    "LCR-048": _task_contract("Freeze the Federal Register Hub and local baseline", "LCR-G100", "LCR-000"),
    "LCR-049": _task_contract("Define the cutoff-bound official Federal Register completeness oracle", "LCR-G100", "LCR-000"),
    "LCR-050": _task_contract("Specify Federal Register v2 identity, admission, and release schemas", "LCR-G100", "LCR-000"),
    "LCR-051": _task_contract("Seal a temporally and agency-diverse Federal Register gold set", "LCR-G100", "LCR-000"),
    "LCR-052": _task_contract("Inventory and acquire the complete official cutoff-bound register", "LCR-G110", "LCR-048, LCR-049, LCR-075"),
    "LCR-053": _task_contract("Acquire official body text and classify every missing-body disposition", "LCR-G110", "LCR-049, LCR-052"),
    "LCR-054": _task_contract("Normalize canonical Federal Register identity and provenance", "LCR-G110", "LCR-050, LCR-052"),
    "LCR-055": _task_contract("Materialize canonical Federal Register corpus, chunks, and recovery", "LCR-G110", "LCR-053, LCR-054"),
    "LCR-056": _task_contract("Build and prove Federal Register term-range BM25", "LCR-G120", "LCR-055"),
    "LCR-057": _task_contract("Generate pinned Federal Register embeddings and true centroid routes", "LCR-G120", "LCR-055"),
    "LCR-058": _task_contract("Build Federal Register agency, rulemaking, citation, and provenance graph", "LCR-G120", "LCR-055, LCR-056"),
    "LCR-059": _task_contract("Implement bounded immutable-Hub Federal Register queries", "LCR-G120", "LCR-056, LCR-057, LCR-058, LCR-076"),
    "LCR-060": _task_contract("Expose Federal Register direct-query package API and CLI", "LCR-G120", "LCR-059"),
    "LCR-061": _task_contract("Implement streaming full and delta Federal Register build orchestration", "LCR-G130", "LCR-056, LCR-057, LCR-058, LCR-076"),
    "LCR-062": _task_contract("Assemble the descriptor-complete Federal Register release and dataset card", "LCR-G130", "LCR-050, LCR-061"),
    "LCR-063": _task_contract("Evaluate Federal Register relevance, recall, graph, security, and determinism", "LCR-G130", "LCR-051, LCR-059, LCR-062"),
    "LCR-064": _task_contract("Upload, redownload, and canary the immutable Federal Register staging candidate", "LCR-G130", "LCR-063, LCR-070, LCR-071, LCR-074"),
    "LCR-065": _task_contract("Authorize and execute the additive Federal Register public upload", "LCR-G140", "LCR-064, LCR-073, LCR-074"),
    "LCR-066": _task_contract("Verify the immutable Federal Register public revision end to end", "LCR-G140", "LCR-065"),
    "LCR-067": _task_contract("Prove shared substrate and vector-space compatibility across both releases", "LCR-G140", "LCR-044, LCR-066"),
    "LCR-068": _task_contract("Rehearse dual-release rollback, updates, and refill closure", "LCR-G140", "LCR-047, LCR-067"),
    "LCR-069": _task_contract("Seal the combined public releases and root-goal evidence", "LCR-G140", "LCR-068"),
}


def _goal_contract(
    title: str,
    parent: str,
    dependencies: str,
    gap_task: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...], str]:
    parents = tuple(item.strip() for item in parent.split(",") if item.strip())
    prerequisites = tuple(
        item.strip() for item in dependencies.split(",") if item.strip()
    )
    return title, parents, prerequisites, gap_task


SEALED_GOAL_CONTRACTS = {
    "LCR-G000": _goal_contract("Publish verified state-law and Federal Register sparse GraphRAG releases", "", "", "LCR-069"),
    "LCR-G010": _goal_contract("Freeze the baseline, authority, identity, and completeness contracts", "LCR-G000", "", "LCR-001"),
    "LCR-G020": _goal_contract("Acquire a complete official corpus for all 51 jurisdictions", "LCR-G000", "LCR-G010", "LCR-023"),
    "LCR-G021": _goal_contract("Complete acquisition cohorts A through D", "LCR-G020", "LCR-G010", "LCR-009"),
    "LCR-G022": _goal_contract("Complete acquisition cohorts E through H", "LCR-G020", "LCR-G010", "LCR-013"),
    "LCR-G023": _goal_contract("Complete acquisition cohorts I through M including DC", "LCR-G020", "LCR-G010", "LCR-017"),
    "LCR-G024": _goal_contract("Reconcile cohort evidence and refill every acquisition gap", "LCR-G020", "LCR-G021, LCR-G022, LCR-G023", "LCR-022"),
    "LCR-G030": _goal_contract("Build a canonical, provenance-rich, bounded state-law corpus", "LCR-G000", "LCR-G010, LCR-G020", "LCR-024"),
    "LCR-G040": _goal_contract("Produce complete sparse, dense, and graph retrieval families", "LCR-G000", "LCR-G030", "LCR-027"),
    "LCR-G050": _goal_contract("Query the immutable Hub release without cloning it", "LCR-G000", "LCR-G040", "LCR-033"),
    "LCR-G060": _goal_contract("Prove legal quality, security, reproducibility, and local end to end behavior", "LCR-G000", "LCR-G030, LCR-G040, LCR-G050", "LCR-035"),
    "LCR-G070": _goal_contract("Stage and canary the exact release candidate", "LCR-G000", "LCR-G060", "LCR-039"),
    "LCR-G080": _goal_contract("Publish and verify the authorized public revision", "LCR-G000", "LCR-G070", "LCR-042"),
    "LCR-G090": _goal_contract("Preserve compatibility, rehearse rollback, and seal final operations evidence", "LCR-G000", "LCR-G080", "LCR-045"),
    "LCR-G100": _goal_contract("Freeze Federal Register baseline, completeness, schema, and gold contracts", "LCR-G000", "", "LCR-048"),
    "LCR-G110": _goal_contract("Acquire and materialize the cutoff-bound Federal Register corpus", "LCR-G000", "LCR-G100", "LCR-052"),
    "LCR-G120": _goal_contract("Build and query Federal Register sparse, dense, and graph families", "LCR-G000", "LCR-G110", "LCR-056"),
    "LCR-G130": _goal_contract("Build, evaluate, stage, and canary the exact Federal Register release", "LCR-G000", "LCR-G100, LCR-G110, LCR-G120", "LCR-061"),
    "LCR-G140": _goal_contract("Publish Federal Register and seal dual-release operations evidence", "LCR-G000", "LCR-G090, LCR-G130", "LCR-065"),
}

JURISDICTIONS = frozenset(
    ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"]
)
COHORTS = {
    "LCR-009": ("A", ("AL", "AK", "AZ", "AR")),
    "LCR-010": ("B", ("CA", "CO", "CT", "DE")),
    "LCR-011": ("C", ("FL", "GA", "HI", "ID")),
    "LCR-012": ("D", ("IL", "IN", "IA", "KS")),
    "LCR-013": ("E", ("KY", "LA", "ME", "MD")),
    "LCR-014": ("F", ("MA", "MI", "MN", "MS")),
    "LCR-015": ("G", ("MO", "MT", "NE", "NV")),
    "LCR-016": ("H", ("NH", "NJ", "NM", "NY")),
    "LCR-017": ("I", ("NC", "ND", "OH", "OK")),
    "LCR-018": ("J", ("OR", "PA", "RI", "SC")),
    "LCR-019": ("K", ("SD", "TN", "TX", "UT")),
    "LCR-020": ("L", ("VT", "VA", "WA", "WV")),
    "LCR-021": ("M", ("WI", "WY", "DC")),
}
JURISDICTION_MODULES = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new_hampshire",
    "NJ": "new_jersey",
    "NM": "new_mexico",
    "NY": "new_york",
    "NC": "north_carolina",
    "ND": "north_dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "RI": "rhode_island",
    "SC": "south_carolina",
    "SD": "south_dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west_virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
    "DC": "district_of_columbia",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _csv(value: str) -> list[str]:
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item.strip() and item.strip().lower() not in {"none", "n/a"}
    ]


def _safe_path(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and value == path.as_posix()


def _task_number(task_id: str) -> int:
    return int(task_id[len(TASK_PREFIX) :])


def _task_lane(task_id: str) -> int:
    """Return the strict lane used by the pinned supervisor runtime."""

    digest_prefix = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8]
    return int(digest_prefix, 16) % 4


def _goal_number(goal_id: str) -> int:
    return int(goal_id[len(GOAL_PREFIX) :])


def _parse_records(
    path: Path,
    heading_pattern: re.Pattern[str],
    *,
    heading_prefix: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    current_id = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return {}, [f"cannot read {path}: {type(exc).__name__}: {exc}"]

    for lineno, line in enumerate(lines, 1):
        if line.startswith(heading_prefix):
            match = heading_pattern.fullmatch(line)
            if not match:
                errors.append(f"{path}:{lineno}: malformed namespaced heading {line!r}")
                current = None
                current_id = ""
                continue
            current_id = match.group(1)
            if current_id in records:
                errors.append(f"{path}:{lineno}: duplicate record {current_id}")
            current = {
                "id": current_id,
                "title": match.group(2).strip(),
                "line": lineno,
            }
            records[current_id] = current
            continue
        if line.startswith("## "):
            current = None
            current_id = ""
            continue
        if current is None or not line.startswith("- "):
            continue
        field = re.fullmatch(r"- ([^:]+):(.*)", line)
        if not field:
            errors.append(f"{path}:{lineno}: malformed metadata line")
            continue
        name = _key(field.group(1))
        if name in current:
            errors.append(f"{path}:{lineno}: duplicate field {name} in {current_id}")
        current[name] = field.group(2).strip()
    return records, errors


def _cycle(graph: Mapping[str, Iterable[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    trail: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            return trail[trail.index(node) :] + [node]
        if node in visited:
            return []
        visiting.add(node)
        trail.append(node)
        for dependency in graph.get(node, ()):
            found = visit(dependency)
            if found:
                return found
        trail.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for item in graph:
        found = visit(item)
        if found:
            return found
    return []


def _transitively_depends(
    task_id: str,
    expected: str,
    graph: Mapping[str, Iterable[str]],
) -> bool:
    pending = list(graph.get(task_id, ()))
    seen: set[str] = set()
    while pending:
        item = pending.pop()
        if item == expected:
            return True
        if item in seen:
            continue
        seen.add(item)
        pending.extend(graph.get(item, ()))
    return False


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() == "true"


def _load_json(path: Path, errors: list[str], noun: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"cannot read {noun} {path}: {type(exc).__name__}: {exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{noun} root must be an object")
        return {}
    return payload


def _validate_cohorts(
    tasks: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> dict[str, list[str]]:
    observed: dict[str, list[str]] = {}
    flattened: list[str] = []
    for task_id, (cohort, expected_codes) in COHORTS.items():
        task = tasks.get(task_id, {})
        title = str(task.get("title") or "")
        match = re.fullmatch(
            rf"Certify full official-source scrape cohort {cohort} \(([^)]+)\)",
            title,
        )
        codes = tuple(_csv(match.group(1))) if match else ()
        observed[cohort] = list(codes)
        flattened.extend(codes)
        if codes != expected_codes:
            errors.append(
                f"{task_id}: cohort {cohort} must be {list(expected_codes)}, got {list(codes)}"
            )
        outputs = set(_csv(str(task.get("outputs") or "")))
        for code in expected_codes:
            module = JURISDICTION_MODULES[code]
            expected_path = (
                "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/"
                f"{module}.py"
            )
            if expected_path not in outputs:
                errors.append(f"{task_id}: missing {code} adapter output {expected_path}")
        receipt = f"docs/reports/legal_corpora_reindex/cohort_{cohort.lower()}.json"
        if receipt not in outputs:
            errors.append(f"{task_id}: missing cohort receipt {receipt}")
    if len(flattened) != 51 or set(flattened) != JURISDICTIONS:
        errors.append(
            "cohort partition must contain each of the 50 states plus DC exactly once; "
            f"count={len(flattened)}, missing={sorted(JURISDICTIONS - set(flattened))}, "
            f"extra={sorted(set(flattened) - JURISDICTIONS)}"
        )
    duplicates = sorted({code for code in flattened if flattened.count(code) > 1})
    if duplicates:
        errors.append(f"cohort partition contains duplicate jurisdictions: {duplicates}")
    return observed


def _validate_config(
    config: Mapping[str, Any],
    *,
    errors: list[str],
) -> None:
    expected_scalars = {
        "schema": "ipfs_accelerate_py.agent_supervisor.legal_corpora_reindex.scheduler_config@1",
        "taskboard_path": TASKBOARD_RELATIVE,
        "objectives_path": OBJECTIVES_RELATIVE,
        "plan_path": PLAN_RELATIVE,
        "validator_path": VALIDATOR_RELATIVE,
        "task_prefix": TASK_PREFIX,
        "goal_prefix": GOAL_PREFIX,
        "board_namespace": BOARD_NAMESPACE,
        "merge_target_branch": "feature/legal-corpora-reindex",
    }
    for field, expected in expected_scalars.items():
        if config.get(field) != expected:
            errors.append(
                f"scheduler {field} mismatch: expected {expected!r}, got {config.get(field)!r}"
            )
    for field in (
        "strict_task_sharding",
        "exit_when_all_tracks_terminal",
        "objective_refill_enabled",
        "codebase_refill_enabled",
    ):
        if config.get(field) is not True:
            errors.append(f"scheduler {field} must be true")
    if config.get("max_lanes") != 4:
        errors.append("scheduler max_lanes must be 4")
    lanes = config.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 4:
        errors.append("scheduler lanes must contain four entries")
    else:
        for index, lane in enumerate(lanes):
            if not isinstance(lane, Mapping):
                errors.append(f"scheduler lanes[{index}] must be an object")
                continue
            if lane.get("index") != index or lane.get("strict_shard_remainder") != index:
                errors.append(f"scheduler lane {index} index/remainder mismatch")
            expected_initial = [
                task_id
                for task_id in SEALED_INITIAL_READY
                if _task_lane(task_id) == index
            ]
            if lane.get("initial_task_ids") != expected_initial:
                errors.append(
                    f"scheduler lane {index} initial_task_ids must be {expected_initial}"
                )

    projection = config.get("initial_projection")
    expected_projection = {
        "task_count": 70,
        "completed_task_ids": list(SEALED_INITIAL_COMPLETED),
        "ready_task_ids": list(SEALED_INITIAL_READY),
        "blocked_task_ids": [],
        "terminal_task_id": "LCR-069",
        "goal_count": len(SEALED_GOAL_IDS),
        "root_goal_id": "LCR-G000",
    }
    if not isinstance(projection, Mapping):
        errors.append("scheduler initial_projection must be an object")
    else:
        for field, expected in expected_projection.items():
            actual = projection.get(field)
            if isinstance(expected, list):
                actual = list(actual) if isinstance(actual, list) else actual
            if actual != expected:
                errors.append(
                    f"scheduler initial_projection.{field} must remain the sealed launch value "
                    f"{expected!r}, got {actual!r}"
                )

    provider = config.get("provider")
    if not isinstance(provider, Mapping):
        errors.append("scheduler provider must be an object")
    else:
        provider_contract = {
            "primary_provider_id": "grok_cli",
            "primary_model_id": "grok-4.5",
            "fallback_provider_id": "codex",
            "fallback_model_id": "gpt-5.6-terra",
            "fallback_trigger": "primary_quota_exhausted",
            "fallback_reasoning_effort": "medium",
            "secrets_from_environment_only": True,
            "secrets_in_argv_prompts_logs_or_receipts": False,
        }
        for field, expected in provider_contract.items():
            if provider.get(field) != expected:
                errors.append(f"scheduler provider.{field} must be {expected!r}")
        concurrency = provider.get("max_concurrency")
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 4:
            errors.append("scheduler provider.max_concurrency must be an integer >= 4")

    protected = config.get("protected_paths")
    required_protected = {
        PLAN_RELATIVE,
        OBJECTIVES_RELATIVE,
        TASKBOARD_RELATIVE,
        CONFIG_RELATIVE,
        VALIDATOR_RELATIVE,
        "tests/unit/supervisor/test_legal_corpora_reindex_board.py",
    }
    protected_is_string_list = isinstance(protected, list) and all(
        isinstance(path, str) for path in protected
    )
    protected_set = set(protected) if protected_is_string_list else set()
    if not protected_is_string_list:
        errors.append("scheduler protected_paths must be a list of strings")
    missing_protected = sorted(required_protected - protected_set)
    if missing_protected:
        errors.append(f"scheduler protected_paths missing {missing_protected}")
    if any(not _safe_path(path) for path in protected_set):
        errors.append("scheduler protected_paths contains an unsafe path")

    source_binding = config.get("source_binding")
    if not isinstance(source_binding, Mapping):
        errors.append("scheduler source_binding must be an object")
    else:
        paired = source_binding.get("paired_accelerator")
        if not isinstance(paired, Mapping):
            errors.append("scheduler source_binding.paired_accelerator must be an object")
        else:
            paired_contract = {
                "sibling_path": "../ipfs_accelerate_py",
                "repository_name": "ipfs_accelerate_py",
                "required_revision": "34420f615d3eebfefa3cc1a3e4ebf8f51b16afac",
                "require_clean_worktree": True,
                "require_exact_revision": True,
            }
            for field, expected in paired_contract.items():
                if paired.get(field) != expected:
                    errors.append(
                        f"scheduler source_binding.paired_accelerator.{field} "
                        f"must be {expected!r}"
                    )

    runtime = config.get("runtime_paths")
    expected_runtime_root = "workspace/agent-supervisor/legal-corpora-reindex"
    if not isinstance(runtime, Mapping):
        errors.append("scheduler runtime_paths must be an object")
    else:
        if runtime.get("root") != expected_runtime_root:
            errors.append(f"scheduler runtime_paths.root must be {expected_runtime_root!r}")
        for field in ("state", "worktrees", "merge_queue", "logs"):
            value = runtime.get(field)
            if not isinstance(value, str) or not _safe_path(value):
                errors.append(f"scheduler runtime_paths.{field} is missing or unsafe")
            elif not value.startswith(f"{expected_runtime_root}/"):
                errors.append(f"scheduler runtime_paths.{field} must be below runtime root")

    authority = config.get("authority_policy")
    if not isinstance(authority, Mapping):
        errors.append("scheduler authority_policy must be an object")
    else:
        required_authority = {
            "exact_jurisdiction_count_required": 51,
            "district_of_columbia_required": True,
            "official_source_and_per_jurisdiction_receipts_required": True,
            "filename_or_nonzero_row_count_proves_completeness": False,
            "publication_authorization_recorded": True,
            "publication_authorized_datasets": list(TARGET_DATASETS),
            "manifest_bound_prepublication_seal_required": True,
            "additional_human_publication_approval_required": False,
            "autonomous_live_dataset_publication_allowed_under_recorded_authorization": True,
        }
        for field, expected in required_authority.items():
            if authority.get(field) != expected:
                errors.append(f"scheduler authority_policy.{field} must be {expected!r}")

    release = config.get("release_policy")
    if not isinstance(release, Mapping):
        errors.append("scheduler release_policy must be an object")
    else:
        required_release = {
            "target_datasets": TARGET_DATASETS,
            "migration_mode": "additive",
            "legacy_artifact_deletion_allowed": False,
            "staging_target_must_be_explicit": True,
            "immutable_redownload_canary_required": True,
            "rollback_rehearsal_required": True,
        }
        for field, expected in required_release.items():
            if release.get(field) != expected:
                errors.append(f"scheduler release_policy.{field} must be {expected!r}")

    refill = config.get("refill_policy")
    if not isinstance(refill, Mapping):
        errors.append("scheduler refill_policy must be an object")
    else:
        required_refill = {
            "initial_population_is_sealed": True,
            "generated_task_number_floor": 70,
            "generated_tasks_must_use_next_numeric_id": True,
            "generated_goals_and_tasks_must_preserve_metadata_contract": True,
            "generated_work_must_bind_discovery_evidence": True,
            "generated_work_must_preserve_output_ownership_and_dependencies": True,
            "deduplicate_equivalent_gaps": True,
            "preserve_terminal_publication_chain": True,
            "refill_on_nonterminal_idle": True,
            "refill_on_acceptance_or_canary_gap": True,
            "minimum_open_tasks": 4,
            "maximum_findings_per_scan": 5,
            "cooldown_seconds": 300,
            "scan_timeout_seconds": 900,
            "objective_task_janitor_enabled": True,
            "objective_goal_completion_reconcile_enabled": True,
            "objective_goal_migration_enabled": False,
        }
        for field, expected in required_refill.items():
            if refill.get(field) != expected:
                errors.append(f"scheduler refill_policy.{field} must be {expected!r}")

    health = config.get("health_policy")
    if not isinstance(health, Mapping):
        errors.append("scheduler health_policy must be an object")
    else:
        required_health = {
            "blocked_tasks_are_unhealthy": True,
            "nonterminal_zero_ready_zero_active_is_unhealthy": True,
            "duplicate_or_orphaned_workers_are_unhealthy": True,
            "protected_path_incidents_are_unhealthy": True,
            "merge_queue_or_provider_errors_are_unhealthy": True,
            "process_liveness_alone_is_healthy": False,
        }
        for field, expected in required_health.items():
            if health.get(field) != expected:
                errors.append(f"scheduler health_policy.{field} must be {expected!r}")
        if health.get("heartbeat_max_age_seconds") != 120:
            errors.append("scheduler health_policy.heartbeat_max_age_seconds must be 120")

    task_groups = config.get("task_groups")
    expected_groups = {
        "LCR-G010": [f"LCR-{number:03d}" for number in range(1, 9)],
        "LCR-G020": [f"LCR-{number:03d}" for number in range(9, 24)],
        "LCR-G021": [f"LCR-{number:03d}" for number in range(9, 13)],
        "LCR-G022": [f"LCR-{number:03d}" for number in range(13, 17)],
        "LCR-G023": [f"LCR-{number:03d}" for number in range(17, 22)],
        "LCR-G024": ["LCR-022", "LCR-023"],
        "LCR-G030": ["LCR-024", "LCR-025", "LCR-026"],
        "LCR-G040": [f"LCR-{number:03d}" for number in range(27, 33)],
        "LCR-G050": ["LCR-033", "LCR-034"],
        "LCR-G060": [f"LCR-{number:03d}" for number in range(35, 39)],
        "LCR-G070": ["LCR-039", "LCR-040", "LCR-041"],
        "LCR-G080": ["LCR-042", "LCR-043", "LCR-044"],
        "LCR-G090": ["LCR-045", "LCR-046", "LCR-047"],
        "LCR-G100": [f"LCR-{number:03d}" for number in range(48, 52)],
        "LCR-G110": [f"LCR-{number:03d}" for number in range(52, 56)],
        "LCR-G120": [f"LCR-{number:03d}" for number in range(56, 61)],
        "LCR-G130": [f"LCR-{number:03d}" for number in range(61, 65)],
        "LCR-G140": [f"LCR-{number:03d}" for number in range(65, 70)],
    }
    if task_groups != expected_groups:
        errors.append("scheduler task_groups do not match the sealed goal/task projection")


def _validate_bundle_policies(
    release_policy: Mapping[str, Any],
    lane_matrix: Mapping[str, Any],
    *,
    errors: list[str],
) -> None:
    if release_policy.get("schema") != "ipfs_datasets_py/legal-corpora-reindex-release-policy@1":
        errors.append("release policy schema mismatch")
    if release_policy.get("dataset_repo_ids") != list(TARGET_DATASETS):
        errors.append("release policy dataset_repo_ids must name the two exact targets")
    if release_policy.get("baseline_revisions") != TARGET_DATASETS:
        errors.append("release policy baseline revisions mismatch")
    if release_policy.get("release_mode") != "additive":
        errors.append("release policy release_mode must be additive")
    jurisdiction = release_policy.get("jurisdiction_contract")
    if not isinstance(jurisdiction, Mapping):
        errors.append("release policy jurisdiction_contract must be an object")
    else:
        codes = jurisdiction.get("required_codes")
        codes_are_strings = isinstance(codes, list) and all(
            isinstance(code, str) for code in codes
        )
        code_set = set(codes) if codes_are_strings else set()
        if not codes_are_strings or len(codes) != 51 or code_set != JURISDICTIONS:
            errors.append("release policy must list the exact 50-state-plus-DC code set")
        codes_are_unique = codes_are_strings and len(codes) == len(code_set)
        if not codes_are_unique:
            errors.append("release policy jurisdiction codes must be unique")
        jurisdiction_contract = {
            "required_count": 51,
            "extra_codes_allowed": False,
            "official_source_receipt_required_per_jurisdiction": True,
            "closed_frontier_required_per_jurisdiction": True,
            "aggregate_and_per_jurisdiction_reconciliation_required": True,
            "failed_final_source_units_allowed_for_publication": False,
        }
        for field, expected in jurisdiction_contract.items():
            if jurisdiction.get(field) != expected:
                errors.append(f"release policy jurisdiction_contract.{field} must be {expected!r}")
    federal = release_policy.get("federal_register_contract")
    if not isinstance(federal, Mapping):
        errors.append("release policy federal_register_contract must be an object")
    else:
        federal_contract = {
            "official_inventory_source": "FederalRegister.gov API",
            "official_full_text_sources": ["FederalRegister.gov", "GovInfo"],
            "immutable_utc_observation_cutoff_required": True,
            "nonoverlapping_date_partition_and_page_closure_required": True,
            "official_total_and_unique_document_number_reconciliation_required": True,
            "typed_body_text_disposition_required_per_document": True,
            "metadata_or_abstract_may_claim_full_text": False,
            "failed_final_documents_allowed_for_publication": False,
            "legacy_delta_start_inclusive": "2026-03-03",
        }
        for field, expected in federal_contract.items():
            if federal.get(field) != expected:
                errors.append(
                    f"release policy federal_register_contract.{field} must be {expected!r}"
                )
    release_bounds = {
        "maximum_rows_per_physical_shard": 4096,
        "maximum_posting_pointers_per_row": 4096,
        "maximum_adjacency_pointers_per_row": 4096,
        "maximum_rows_per_vector_centroid": 8192,
        "maximum_vector_shards_per_centroid": 2,
        "legacy_artifact_deletion_allowed": False,
        "streaming_checkpointed_build_required": True,
        "immutable_hub_revision_required_for_query": True,
        "descriptor_verification_required_before_parse": True,
    }
    for field, expected in release_bounds.items():
        if release_policy.get(field) != expected:
            errors.append(f"release policy {field} must be {expected!r}")
    required_families = {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "vectors",
        "vector_centroid_routes",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency_out",
        "graph_adjacency_in",
        "locators",
        "recovery_quarantine",
    }
    families = release_policy.get("required_semantic_families")
    families_are_strings = isinstance(families, list) and all(
        isinstance(family, str) for family in families
    )
    if not families_are_strings or set(families) != required_families:
        errors.append("release policy required_semantic_families mismatch")
    publication = release_policy.get("publication_authorization")
    if not isinstance(publication, Mapping):
        errors.append("release policy publication_authorization must be an object")
    else:
        publication_contract = {
            "status": "recorded",
            "recorded_on": "2026-08-10",
            "authorized_dataset_repo_ids": list(TARGET_DATASETS),
            "manifest_bound_prepublication_seal_required": True,
            "additional_human_approval_required": False,
            "alternate_dataset_targets_allowed": False,
            "deletion_allowed": False,
            "force_push_allowed": False,
            "history_rewrite_allowed": False,
            "visibility_change_allowed": False,
        }
        for field, expected in publication_contract.items():
            if publication.get(field) != expected:
                errors.append(f"release policy publication_authorization.{field} must be {expected!r}")

    prepublication = release_policy.get("prepublication_evidence_contract")
    if not isinstance(prepublication, Mapping):
        errors.append("release policy prepublication_evidence_contract must be an object")
    else:
        prepublication_contract = {
            "required_task_ids": [f"LCR-{number:03d}" for number in range(70, 77)],
            "required_receipts": [
                "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json",
                "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json",
                "docs/reports/legal_corpora_reindex/state_prepublication_seal.json",
                "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json",
                "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.json",
            ],
            "applies_to_dataset_repo_ids": list(TARGET_DATASETS),
            "fixture_only_evidence_allowed": False,
            "authenticated_live_hub_snapshot_required": True,
            "local_salvage_inventory_required": True,
            "receipt_content_digests_required": True,
            "publication_gate_module": (
                "ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate"
            ),
            "required_before_state_staging_task_ids": ["LCR-070", "LCR-074"],
            "required_before_state_main_task_ids": ["LCR-070", "LCR-072", "LCR-074"],
            "required_before_federal_staging_task_ids": [
                "LCR-070",
                "LCR-071",
                "LCR-074",
                "LCR-075",
                "LCR-076",
            ],
            "required_before_federal_main_task_ids": [
                "LCR-070",
                "LCR-071",
                "LCR-073",
                "LCR-074",
                "LCR-075",
                "LCR-076",
            ],
            "uploader_must_invoke_gate_before_first_network_mutation": True,
            "prepublication_seal_must_precede_main_mutation": True,
        }
        for field, expected in prepublication_contract.items():
            if prepublication.get(field) != expected:
                errors.append(
                    f"release policy prepublication_evidence_contract.{field} "
                    f"must be {expected!r}"
                )

    if lane_matrix.get("schema") != "ipfs_datasets_py/legal-corpora-reindex-lane-matrix@1":
        errors.append("lane matrix schema mismatch")
    if lane_matrix.get("board_namespace") != BOARD_NAMESPACE:
        errors.append("lane matrix board namespace mismatch")
    expected_shard_rule = "sha256_full_task_id_first_8_hex_modulo_4"
    if lane_matrix.get("shard_rule") != expected_shard_rule:
        errors.append(f"lane matrix shard_rule must be {expected_shard_rule}")
    lanes = lane_matrix.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != 4:
        errors.append("lane matrix must contain four lanes")
    else:
        observed: list[str] = []
        for index, lane in enumerate(lanes):
            if not isinstance(lane, Mapping) or lane.get("index") != index:
                errors.append(f"lane matrix lane {index} index mismatch")
                continue
            expected_ids = [
                task_id for task_id in SEALED_TASK_IDS if _task_lane(task_id) == index
            ]
            if lane.get("task_ids") != expected_ids:
                errors.append(f"lane matrix lane {index} task_ids mismatch")
            expected_initial = [
                task_id for task_id in SEALED_INITIAL_READY if _task_lane(task_id) == index
            ]
            if lane.get("initial_task_ids") != expected_initial:
                errors.append(f"lane matrix lane {index} initial_task_ids mismatch")
            lane_task_ids = lane.get("task_ids")
            if isinstance(lane_task_ids, list) and all(
                isinstance(task_id, str) for task_id in lane_task_ids
            ):
                observed.extend(lane_task_ids)
            else:
                errors.append(f"lane matrix lane {index} task_ids must be strings")
        if sorted(observed) != sorted(SEALED_TASK_IDS):
            errors.append("lane matrix must cover every sealed task exactly once")
    for field in (
        "generated_task_lane_rule_is_authoritative",
        "protected_control_plane",
        "serialized_merge_queue",
        "cross_lane_dependencies_are_authoritative",
    ):
        if lane_matrix.get(field) is not True:
            errors.append(f"lane matrix {field} must be true")


def validate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    todo_path = root / TASKBOARD_RELATIVE
    objectives_path = root / OBJECTIVES_RELATIVE
    plan_path = root / PLAN_RELATIVE
    config_path = root / CONFIG_RELATIVE
    task_pattern = re.compile(r"## (LCR-(?:\d{3}|\d{4,})) (\S.+)")
    goal_pattern = re.compile(r"## (LCR-G(?:\d{3}|\d{4,})) (\S.+)")
    tasks, errors = _parse_records(
        todo_path,
        task_pattern,
        heading_prefix="## LCR-",
    )
    goals, goal_errors = _parse_records(
        objectives_path,
        goal_pattern,
        heading_prefix="## LCR-G",
    )
    errors.extend(goal_errors)
    warnings: list[str] = []

    missing_tasks = sorted(set(SEALED_TASK_IDS) - set(tasks))
    if missing_tasks:
        errors.append(f"sealed initial tasks are missing: {missing_tasks}")
    unexpected_low_tasks = sorted(
        task_id
        for task_id in tasks
        if task_id not in SEALED_TASK_CONTRACTS and _task_number(task_id) < 70
    )
    if unexpected_low_tasks:
        errors.append(f"unrecognized task IDs below continuation boundary: {unexpected_low_tasks}")
    generated_task_numbers = sorted(
        _task_number(task_id) for task_id in tasks if _task_number(task_id) >= 70
    )
    if generated_task_numbers:
        expected = list(range(70, generated_task_numbers[-1] + 1))
        if generated_task_numbers != expected:
            errors.append(
                "generated task IDs must be contiguous from LCR-070; "
                f"expected={expected}, got={generated_task_numbers}"
            )

    missing_goals = sorted(set(SEALED_GOAL_IDS) - set(goals))
    if missing_goals:
        errors.append(f"sealed initial goals are missing: {missing_goals}")
    unexpected_low_goals = sorted(
        goal_id
        for goal_id in goals
        if goal_id not in SEALED_GOAL_CONTRACTS and _goal_number(goal_id) < 141
    )
    if unexpected_low_goals:
        errors.append(f"unrecognized goal IDs below continuation boundary: {unexpected_low_goals}")
    generated_goal_numbers = sorted(
        _goal_number(goal_id) for goal_id in goals if _goal_number(goal_id) >= 141
    )
    if generated_goal_numbers:
        expected = list(range(141, generated_goal_numbers[-1] + 1))
        if generated_goal_numbers != expected:
            errors.append(
                "generated goal IDs must be contiguous from LCR-G141; "
                f"expected={expected}, got={generated_goal_numbers}"
            )

    goal_graph: dict[str, list[str]] = {}
    for goal_id, goal in goals.items():
        initial = goal_id in SEALED_GOAL_CONTRACTS
        fields = set(goal) - {"id", "title", "line"}
        if initial:
            missing = sorted(GOAL_FIELDS - fields)
            extra = sorted(fields - GOAL_FIELDS)
            if missing:
                errors.append(f"{goal_id}: missing sealed goal fields {missing}")
            if extra:
                errors.append(f"{goal_id}: unexpected sealed goal fields {extra}")
        else:
            missing = sorted(GENERATED_GOAL_FIELDS - fields)
            if missing:
                errors.append(f"{goal_id}: missing generated goal fields {missing}")
            if "refinement" not in fields and "refinement_depth" not in fields:
                errors.append(f"{goal_id}: generated goal needs Refinement or Refinement depth")

        status = str(goal.get("status") or "").lower()
        if status not in GOAL_STATUS_VALUES:
            errors.append(f"{goal_id}: unsupported goal status {status!r}")
        try:
            if int(str(goal.get("fib_priority") or "0")) <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"{goal_id}: Fib priority must be a positive integer")
        for field in (
            "track",
            "priority",
            "bundle",
            "goal",
            "evidence",
            "validation",
            "acceptance",
            "gap_task",
            "embedding_query",
            "ast_query",
            "parallel_lane",
            "conflict_policy",
        ):
            if not str(goal.get(field) or "").strip():
                errors.append(f"{goal_id}: {field} must be nonempty")
        outputs = _csv(str(goal.get("outputs") or ""))
        if not outputs:
            errors.append(f"{goal_id}: Outputs must be nonempty")
        for output in outputs:
            if not _safe_path(output):
                errors.append(f"{goal_id}: unsafe output path {output!r}")

        parents = _csv(str(goal.get("parent") or ""))
        dependencies = _csv(str(goal.get("depends_on") or ""))
        goal_graph[goal_id] = [*parents, *dependencies]
        if goal_id == "LCR-G000" and parents:
            errors.append("LCR-G000 must not have a parent")
        if not initial and not parents:
            errors.append(f"{goal_id}: generated goal must refine an existing parent")
        for reference in [*parents, *dependencies]:
            if reference not in goals:
                errors.append(f"{goal_id}: unknown goal reference {reference}")
            elif reference == goal_id:
                errors.append(f"{goal_id}: self-referential goal dependency")

        if initial:
            title, expected_parents, expected_dependencies, expected_gap = (
                SEALED_GOAL_CONTRACTS[goal_id]
            )
            if goal.get("title") != title:
                errors.append(f"{goal_id}: sealed title mismatch")
            if tuple(parents) != expected_parents:
                errors.append(f"{goal_id}: sealed parent contract changed")
            if tuple(dependencies) != expected_dependencies:
                errors.append(f"{goal_id}: sealed goal dependency contract changed")
            if goal.get("gap_task") != expected_gap:
                errors.append(f"{goal_id}: sealed Gap task must be {expected_gap}")

    found_goal_cycle = _cycle(goal_graph)
    if found_goal_cycle:
        errors.append(f"goal hierarchy/dependency cycle: {' -> '.join(found_goal_cycle)}")

    task_graph: dict[str, list[str]] = {}
    completed: set[str] = set()
    blocked: set[str] = set()
    in_progress: set[str] = set()
    output_owners: dict[str, list[str]] = defaultdict(list)
    protected_initial_outputs = set(
        _csv(str(tasks.get("LCR-000", {}).get("outputs") or ""))
    )
    for task_id, task in tasks.items():
        initial = task_id in SEALED_TASK_CONTRACTS
        fields = set(task) - {"id", "title", "line"}
        required_fields = TASK_FIELDS if initial else GENERATED_TASK_FIELDS
        missing = sorted(required_fields - fields)
        if missing:
            errors.append(f"{task_id}: missing task fields {missing}")
        if initial:
            extra = sorted(fields - TASK_FIELDS)
            if extra:
                errors.append(f"{task_id}: unexpected sealed task fields {extra}")

        status = str(task.get("status") or "").lower()
        if status not in TASK_STATUS_VALUES:
            errors.append(f"{task_id}: unsupported task status {status!r}")
        if status == "completed":
            completed.add(task_id)
        elif status == "blocked":
            blocked.add(task_id)
        elif status == "in_progress":
            in_progress.add(task_id)
        if str(task.get("completion") or "").lower() not in COMPLETION_VALUES:
            errors.append(f"{task_id}: unsupported Completion value")
        for field in ("is_schedulable", "review_only"):
            if (initial or field in task) and str(task.get(field) or "").lower() not in {"true", "false"}:
                errors.append(f"{task_id}: {field} must be true or false")
        if not re.fullmatch(r"P[0-9]", str(task.get("priority") or "")):
            errors.append(f"{task_id}: Priority must be P followed by one digit")
        required_nonempty = (
            (
                "track",
                "goal_id",
                "validation",
                "bundle",
                "resource_class",
                "token_class",
                "conflict_policy",
                "preconditions",
                "effects",
                "acceptance",
                "generated_by",
            )
            if initial
            else ("track", "goal_id", "validation", "acceptance")
        )
        for field in required_nonempty:
            if not str(task.get(field) or "").strip():
                errors.append(f"{task_id}: {field} must be nonempty")
        if initial or "estimated_tokens" in task:
            try:
                token_estimate = int(str(task.get("estimated_tokens") or "0"))
                if token_estimate < (1 if initial else 0):
                    raise ValueError
            except ValueError:
                errors.append(
                    f"{task_id}: Estimated tokens must be a "
                    f"{'positive' if initial else 'nonnegative'} integer"
                )
        if task.get("board_namespace") != BOARD_NAMESPACE:
            errors.append(f"{task_id}: Board namespace must be {BOARD_NAMESPACE}")
        expected_lane = _task_lane(task_id)
        if initial:
            try:
                lane = int(str(task.get("parallel_lane")))
            except ValueError:
                lane = -1
            if lane != expected_lane:
                errors.append(
                    f"{task_id}: Parallel lane {lane} must equal the full-task-ID "
                    f"SHA-256 rule ({expected_lane})"
                )

        goal_id = str(task.get("goal_id") or "")
        if goal_id not in goals:
            errors.append(f"{task_id}: unknown Goal id {goal_id!r}")
        dependencies = _csv(str(task.get("depends_on") or ""))
        task_graph[task_id] = dependencies
        for dependency in dependencies:
            if dependency not in tasks:
                errors.append(f"{task_id}: unknown task dependency {dependency}")
            elif dependency == task_id:
                errors.append(f"{task_id}: self dependency")
        outputs = _csv(str(task.get("outputs") or ""))
        predicted = _csv(str(task.get("predicted_files") or ""))
        if initial and outputs != predicted:
            errors.append(f"{task_id}: Outputs and Predicted files must match exactly")
        if not outputs:
            errors.append(f"{task_id}: Outputs must be nonempty")
        owned_outputs = outputs if initial or not predicted else predicted
        for output in outputs:
            if not _safe_path(output):
                errors.append(f"{task_id}: unsafe output path {output!r}")
            if not initial and output in protected_initial_outputs:
                errors.append(
                    f"{task_id}: continuation task cannot own protected control path {output}"
                )
        for output in owned_outputs:
            if _safe_path(output):
                output_owners[output].append(task_id)
        for peer in _csv(str(task.get("allow_concurrent_with") or "")):
            if peer not in tasks:
                errors.append(f"{task_id}: unknown Allow concurrent with task {peer}")
            elif peer == task_id:
                errors.append(f"{task_id}: cannot allow concurrency with itself")

        generated_by = str(task.get("generated_by") or "")
        if initial:
            title, expected_goal, expected_dependencies = SEALED_TASK_CONTRACTS[task_id]
            if task.get("title") != title:
                errors.append(f"{task_id}: sealed title mismatch")
            if goal_id != expected_goal:
                errors.append(f"{task_id}: sealed Goal id must remain {expected_goal}")
            if tuple(dependencies) != expected_dependencies:
                errors.append(f"{task_id}: sealed dependency contract changed")
            if generated_by != "sealed-initial-plan":
                errors.append(f"{task_id}: Generated by must remain sealed-initial-plan")
            if str(task.get("completion") or "").lower() != "evidence":
                errors.append(f"{task_id}: sealed Completion must remain evidence")
            if task.get("priority") != "P0":
                errors.append(f"{task_id}: sealed Priority must remain P0")
            if str(task.get("review_only") or "").lower() != "false":
                errors.append(f"{task_id}: sealed Review only must remain false")
            expected_schedulable = task_id != "LCR-000"
            if _is_true(task.get("is_schedulable")) != expected_schedulable:
                errors.append(
                    f"{task_id}: sealed schedulable flag must be "
                    f"{str(expected_schedulable).lower()}"
                )
        else:
            if generated_by == "sealed-initial-plan":
                errors.append(f"{task_id}: continuation cannot claim sealed-initial-plan")
            if (
                status == "todo"
                and "is_schedulable" in task
                and not _is_true(task.get("review_only"))
                and not _is_true(task.get("is_schedulable"))
            ):
                errors.append(
                    f"{task_id}: executable todo continuation must be schedulable or review-only"
                )

    found_task_cycle = _cycle(task_graph)
    if found_task_cycle:
        errors.append(f"task dependency cycle: {' -> '.join(found_task_cycle)}")

    required_terminal_ancestry = [
        *[f"LCR-{number:03d}" for number in range(69)],
        *[f"LCR-{number:03d}" for number in range(70, 77)],
    ]
    for task_id in required_terminal_ancestry:
        if task_id not in tasks:
            errors.append(f"terminal ancestry task is missing: {task_id}")
        elif not _transitively_depends("LCR-069", task_id, task_graph):
            errors.append(f"LCR-069 must transitively depend on {task_id}")

    for output, owners in sorted(output_owners.items()):
        if len(owners) < 2:
            continue
        for left_index, left in enumerate(owners):
            for right in owners[left_index + 1 :]:
                if not (
                    _transitively_depends(left, right, task_graph)
                    or _transitively_depends(right, left, task_graph)
                ):
                    errors.append(f"unordered output collision for {output}: {left}, {right}")

    cohort_projection = _validate_cohorts(tasks, errors)

    ready = sorted(
        task_id
        for task_id, task in tasks.items()
        if str(task.get("status") or "").lower() == "todo"
        and (
            _is_true(task.get("is_schedulable"))
            if "is_schedulable" in task
            else not _is_true(task.get("review_only"))
        )
        and all(dependency in completed for dependency in task_graph.get(task_id, ()))
    )
    waiting = sorted(
        task_id
        for task_id, task in tasks.items()
        if str(task.get("status") or "").lower() == "todo"
        and task_id not in ready
    )

    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"cannot read plan {plan_path}: {type(exc).__name__}: {exc}")
        plan_text = ""
    for required_term in (
        *TARGET_DATASETS,
        *TARGET_DATASETS.values(),
        "50 states and the District of Columbia",
        "`LCR-000`–`LCR-069`",
        "sha256(full_task_id)",
        "objective and codebase refill scans are enabled",
        "immutable public revision",
    ):
        if required_term not in plan_text:
            errors.append(f"plan missing required contract term {required_term!r}")

    config = _load_json(config_path, errors, "scheduler config")
    if config:
        _validate_config(config, errors=errors)
    release_policy = _load_json(
        root / RELEASE_POLICY_RELATIVE,
        errors,
        "release policy",
    )
    lane_matrix = _load_json(
        root / LANE_MATRIX_RELATIVE,
        errors,
        "lane matrix",
    )
    if release_policy and lane_matrix:
        _validate_bundle_policies(
            release_policy,
            lane_matrix,
            errors=errors,
        )

    current_projection = {
        "task_count": len(tasks),
        "goal_count": len(goals),
        "completed_task_ids": sorted(completed),
        "ready_task_ids": ready,
        "waiting_task_ids": waiting,
        "blocked_task_ids": sorted(blocked),
        "in_progress_task_ids": sorted(in_progress),
        "continuation_task_ids": sorted(
            task_id for task_id in tasks if _task_number(task_id) >= 70
        ),
        "continuation_goal_ids": sorted(
            goal_id for goal_id in goals if _goal_number(goal_id) >= 141
        ),
    }
    unique_outputs = set(output_owners)
    return {
        "schema": "ipfs_datasets_py/legal-corpora-reindex-board-validation@1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "tasks": len(tasks),
            "sealed_tasks": sum(task_id in SEALED_TASK_CONTRACTS for task_id in tasks),
            "continuation_tasks": sum(_task_number(task_id) >= 70 for task_id in tasks),
            "goals": len(goals),
            "sealed_goals": sum(goal_id in SEALED_GOAL_CONTRACTS for goal_id in goals),
            "continuation_goals": sum(_goal_number(goal_id) >= 141 for goal_id in goals),
            "completed": len(completed),
            "ready": len(ready),
            "waiting": len(waiting),
            "blocked": len(blocked),
            "in_progress": len(in_progress),
            "outputs": len(unique_outputs),
            "jurisdictions": len({code for codes in cohort_projection.values() for code in codes}),
        },
        "current_projection": current_projection,
        "cohorts": cohort_projection,
        "lane_task_counts": {
            str(lane): sum(_task_lane(task_id) == lane for task_id in tasks)
            for lane in range(4)
        },
        "sealed_initial_projection": {
            "task_count": len(SEALED_TASK_IDS),
            "goal_count": len(SEALED_GOAL_IDS),
            "completed_task_ids": list(SEALED_INITIAL_COMPLETED),
            "ready_task_ids": list(SEALED_INITIAL_READY),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-all",
        action="store_true",
        help="Validate every sealed and refill-aware control-plane invariant.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args(argv)
    report = validate(args.repo_root)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
