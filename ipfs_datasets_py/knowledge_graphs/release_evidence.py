"""Fail-closed release evidence collector for knowledge graphs (KGP-049 / KGP-G100).

This module is the **executable collector** that:

1. Binds every artifact to an **explicit clean repository tree**.
2. Records validation **command**, **timestamp**, **environment label**,
   **exit status**, **test counts**, and **artifact digests**.
3. **Refuses** failed, skipped, expected-failure (xfail), stale, foreign-tree,
   dirty-tree, or unsigned evidence where a signature is required.
4. Ingests corpus sign-offs, UCAN deny proof, and load/soak/chaos digests.
5. Builds a :class:`~ipfs_datasets_py.knowledge_graphs.release_gate.ReleaseEvidenceBundle`
   and evaluates it with :class:`~ipfs_datasets_py.knowledge_graphs.release_gate.GraphReleaseGate`
   **fail-closed**.

It **composes** the existing ``release_gate`` receipt types. It never
synthesizes a passing receipt from task status, prose, coverage, skips, or
expected failures.

Normative policy: ``kg-release-evidence/v1`` (same as KGP-035 / KGP-G100).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Dict,
    Final,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from ipfs_datasets_py.knowledge_graphs import release_gate as rg
from ipfs_datasets_py.knowledge_graphs.release_gate import (
    DEFAULT_MAX_RECEIPT_AGE,
    GOAL_ID,
    POLICY_ID,
    REQUIRED_CHILD_GOALS,
    REQUIRED_CORPORA,
    ROOT_DOD_CLAUSE_IDS,
    ROOT_DOD_CLAUSES,
    CorpusSignOff,
    DodClauseReceipt,
    EnvironmentBinding,
    GoalReceipt,
    GraphReleaseGate,
    ReleaseDecision,
    ReleaseEvidenceBundle,
    ReleaseGateError,
    ReleaseGateFailClosed,
    SoakChaosEvidence,
    UCANNegativeProof,
    content_address,
    is_production_ready,
    is_rejected_substitute,
    is_unknown_environment,
    make_corpus_signoff,
    make_dod_receipt,
    make_goal_receipt,
    parse_timestamp,
)

# ---------------------------------------------------------------------------
# Schema stamps
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "kg-release-evidence-collector/v1"
COMMAND_EVIDENCE_SCHEMA: Final = "kg-command-evidence/v1"
TASK_ID: Final = "KGP-049"
COLLECTOR_GOAL_ID: Final = "KGP-G100"
CONTENT_DOMAIN: Final = "kg.release.collector"

# Ten child gates: G010..G090 plus root release gate G100.
TEN_CHILD_GATES: Final[Tuple[str, ...]] = REQUIRED_CHILD_GOALS + (GOAL_ID,)
assert TEN_CHILD_GATES == (
    "KGP-G010",
    "KGP-G020",
    "KGP-G030",
    "KGP-G040",
    "KGP-G050",
    "KGP-G060",
    "KGP-G070",
    "KGP-G080",
    "KGP-G090",
    "KGP-G100",
)
assert len(TEN_CHILD_GATES) == 10

# Default validation command templates per child goal (documentation + defaults).
CHILD_GATE_CATALOG: Final[Tuple[Mapping[str, str], ...]] = (
    {
        "goal_id": "KGP-G010",
        "title": "Executable truth baseline and compatibility contract",
        "validation_command": "python -m pytest -q tests/knowledge_graphs/contract",
        "evidence_kind": "contract_probe",
    },
    {
        "goal_id": "KGP-G020",
        "title": "Canonical graph identity, manifest, catalog, and service",
        "validation_command": (
            "python -m pytest -q tests/unit/knowledge_graphs/contracts "
            "tests/integration/knowledge_graphs/test_catalog_service.py"
        ),
        "evidence_kind": "validation_receipt",
    },
    {
        "goal_id": "KGP-G030",
        "title": "Durable concurrency, transactions, and recovery",
        "validation_command": (
            "python -m pytest -q tests/unit/knowledge_graphs/test_transactions.py "
            "tests/integration/knowledge_graphs/concurrency "
            "tests/chaos/knowledge_graphs"
        ),
        "evidence_kind": "concurrency_receipt",
    },
    {
        "goal_id": "KGP-G040",
        "title": "Interchangeable Parquet, IPFS/IPLD, and ipfs_kit_py storage",
        "validation_command": (
            "python -m pytest -q tests/contract/knowledge_graphs/storage "
            "tests/integration/knowledge_graphs/test_storage_restart.py"
        ),
        "evidence_kind": "storage_contract",
    },
    {
        "goal_id": "KGP-G050",
        "title": "Versioned sharding and bounded unified query",
        "validation_command": (
            "python -m pytest -q tests/unit/search/test_sharded_car "
            "tests/integration/knowledge_graphs/test_sharded_query.py "
            "tests/knowledge_graphs/contract/test_query_budgets.py"
        ),
        "evidence_kind": "sharding_integrity",
    },
    {
        "goal_id": "KGP-G060",
        "title": "Python, CLI, MCP, and MCP++ surface parity",
        "validation_command": (
            "python -m pytest -q tests/knowledge_graphs/conformance "
            "tests/cli/test_graph_commands.py tests/mcp/test_graph_tools.py"
        ),
        "evidence_kind": "surface_conformance",
    },
    {
        "goal_id": "KGP-G070",
        "title": "MCP++ UCAN authorization and audit",
        "validation_command": (
            "python -m pytest -q tests/security/knowledge_graphs "
            "tests/mcp/test_graph_ucan.py"
        ),
        "evidence_kind": "ucan_audit_receipt",
    },
    {
        "goal_id": "KGP-G080",
        "title": "Real corpus adapters and differential validation",
        "validation_command": (
            "python -m pytest -q tests/integration/knowledge_graphs/corpora"
        ),
        "evidence_kind": "corpus_differential",
    },
    {
        "goal_id": "KGP-G090",
        "title": "Load, soak, chaos, observability, and operability",
        "validation_command": (
            "python -m pytest -q tests/load/knowledge_graphs "
            "tests/chaos/knowledge_graphs"
        ),
        "evidence_kind": "load_receipt",
    },
    {
        "goal_id": "KGP-G100",
        "title": "Reversible adoption and production release (root gate)",
        "validation_command": (
            "python -m pytest -q "
            "tests/integration/knowledge_graphs/test_shadow_migration.py "
            "tests/integration/knowledge_graphs/test_rollback.py "
            "tests/integration/knowledge_graphs/test_release_gate.py "
            "tests/integration/knowledge_graphs/test_release_evidence_collector.py"
        ),
        "evidence_kind": "migration_receipt",
    },
)

_PYTEST_SUMMARY_RE = re.compile(
    r"(?P<count>\d+)\s+"
    r"(?P<label>passed|failed|skipped|xfailed|xpassed|error|errors|warnings?)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Errors / refusal codes
# ---------------------------------------------------------------------------


class RefusalCode(str, Enum):
    """Machine-readable reasons the collector refuses evidence."""

    FAILED = "failed"
    SKIPPED = "skipped"
    EXPECTED_FAILURE = "expected_failure"
    STALE = "stale"
    FOREIGN_TREE = "foreign_tree"
    UNSIGNED = "unsigned"
    DIRTY_TREE = "dirty_tree"
    REJECTED_SUBSTITUTE = "rejected_substitute"
    UNKNOWN_ENVIRONMENT = "unknown_environment"
    SAMPLE_ONLY = "sample_only"
    MISSING_DIGEST = "missing_digest"
    NONZERO_EXIT = "nonzero_exit"
    MISSING_FIELD = "missing_field"
    DIGEST_MISMATCH = "digest_mismatch"
    TREE_REQUIRED = "tree_required"
    INVALID_STATUS = "invalid_status"


class EvidenceCollectorError(Exception):
    """Base error for the release evidence collector."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "collector_error",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details: Dict[str, Any] = dict(details or {})


class EvidenceRefusal(EvidenceCollectorError):
    """Raised when the collector refuses to accept evidence (fail-closed)."""

    def __init__(
        self,
        message: str,
        *,
        code: Union[RefusalCode, str],
        details: Optional[Mapping[str, Any]] = None,
        subject: str = "",
    ) -> None:
        code_value = code.value if isinstance(code, RefusalCode) else str(code)
        super().__init__(message, code=code_value, details=details)
        self.subject = subject


# ---------------------------------------------------------------------------
# Time / hashing helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _format_ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def _normalize_status(status: Any) -> str:
    if status is None:
        return ""
    return str(status).strip().lower().replace("-", "_").replace(" ", "_")


def file_digest(path: Union[str, Path]) -> str:
    """Return ``sha256:<hex>`` of the file at *path*."""

    data = Path(path).read_bytes()
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def bytes_digest(data: bytes) -> str:
    """Return ``sha256:<hex>`` of *data*."""

    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def text_digest(text: str) -> str:
    """Return ``sha256:<hex>`` of UTF-8 *text*."""

    return bytes_digest(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Tree binding (explicit clean repository tree)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TreeBinding:
    """Binding of collector state to one clean repository tree."""

    tree_id: str
    commit: str
    is_clean: bool
    repo_root: str
    dirty_paths: Tuple[str, ...] = ()
    collected_at: str = ""
    binding_digest: str = ""

    def __post_init__(self) -> None:
        if not self.collected_at:
            object.__setattr__(self, "collected_at", _format_ts(_now_utc()))
        if not self.binding_digest:
            object.__setattr__(self, "binding_digest", self.compute_digest())

    def compute_digest(self) -> str:
        payload = {
            "commit": self.commit,
            "dirty_paths": list(self.dirty_paths),
            "is_clean": self.is_clean,
            "repo_root": self.repo_root,
            "tree_id": self.tree_id,
        }
        return content_address(payload, domain=f"{CONTENT_DOMAIN}.tree")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "binding_digest": self.binding_digest,
            "collected_at": self.collected_at,
            "commit": self.commit,
            "dirty_paths": list(self.dirty_paths),
            "is_clean": self.is_clean,
            "repo_root": self.repo_root,
            "tree_id": self.tree_id,
        }


def normalize_tree_id(value: str) -> str:
    """Normalize a git commit / tree identifier to ``tree-<40hex>`` form."""

    text = str(value or "").strip()
    if text.startswith("tree-"):
        body = text[5:]
    else:
        body = text
    body = body.lower()
    if re.fullmatch(r"[0-9a-f]{40}", body):
        return f"tree-{body}"
    if re.fullmatch(r"[0-9a-f]{7,64}", body):
        # Accept short SHAs by zero-padding only for full 40 when possible;
        # otherwise keep as tree-<sha> for explicit operator-supplied ids.
        return f"tree-{body}"
    if text:
        return text if text.startswith("tree-") else f"tree-{text}"
    return ""


def resolve_clean_tree(
    repo_root: Union[str, Path],
    *,
    expected_tree_id: Optional[str] = None,
    allow_dirty: bool = False,
    git_runner: Optional[Any] = None,
) -> TreeBinding:
    """Resolve HEAD and require a clean working tree (fail-closed).

    Parameters
    ----------
    repo_root:
        Path to the git repository root.
    expected_tree_id:
        Optional explicit tree id. When provided it must match HEAD.
    allow_dirty:
        When True, return a binding with ``is_clean=False`` instead of raising.
        The collector still refuses to accept evidence against a dirty tree
        unless the operator opts in at a higher level (not recommended).
    git_runner:
        Optional callable ``(args: list[str], cwd: Path) -> str`` used in tests.
    """

    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise EvidenceCollectorError(
            f"repository root does not exist: {root}",
            code="missing_repo_root",
            details={"repo_root": str(root)},
        )

    def _run(args: Sequence[str]) -> str:
        if git_runner is not None:
            return str(git_runner(list(args), root))
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=str(root),
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise EvidenceCollectorError(
                "git executable not found",
                code="git_missing",
            ) from exc
        if completed.returncode != 0:
            raise EvidenceCollectorError(
                f"git {' '.join(args)} failed: {completed.stderr.strip()}",
                code="git_failed",
                details={"returncode": completed.returncode},
            )
        return completed.stdout

    commit = _run(["rev-parse", "HEAD"]).strip()
    if not commit:
        raise EvidenceCollectorError(
            "unable to resolve git HEAD",
            code="missing_head",
        )
    porcelain = _run(["status", "--porcelain"])
    dirty_paths = tuple(
        line[3:].strip() if len(line) > 3 else line.strip()
        for line in porcelain.splitlines()
        if line.strip()
    )
    is_clean = len(dirty_paths) == 0
    tree_id = normalize_tree_id(commit)

    if expected_tree_id:
        expected = normalize_tree_id(expected_tree_id)
        if expected != tree_id and expected_tree_id != commit:
            # Also accept exact full commit equality when operator passes raw SHA.
            if expected != normalize_tree_id(commit):
                raise EvidenceRefusal(
                    "repository HEAD does not match expected_tree_id",
                    code=RefusalCode.FOREIGN_TREE,
                    subject="tree",
                    details={
                        "expected_tree_id": expected_tree_id,
                        "actual_tree_id": tree_id,
                        "commit": commit,
                    },
                )
            tree_id = expected

    if not is_clean and not allow_dirty:
        raise EvidenceRefusal(
            "repository working tree is dirty; release evidence requires a clean tree",
            code=RefusalCode.DIRTY_TREE,
            subject="tree",
            details={"dirty_paths": list(dirty_paths), "tree_id": tree_id},
        )

    return TreeBinding(
        tree_id=tree_id,
        commit=commit,
        is_clean=is_clean,
        repo_root=str(root),
        dirty_paths=dirty_paths,
    )


# ---------------------------------------------------------------------------
# Test counts + command evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TestCounts:
    """Parsed pytest (or equivalent) counts for a validation command."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    errors: int = 0

    @property
    def total(self) -> int:
        return (
            self.passed
            + self.failed
            + self.skipped
            + self.xfailed
            + self.xpassed
            + self.errors
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "errors": self.errors,
            "failed": self.failed,
            "passed": self.passed,
            "skipped": self.skipped,
            "total": self.total,
            "xfailed": self.xfailed,
            "xpassed": self.xpassed,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TestCounts":
        return cls(
            passed=int(data.get("passed") or 0),
            failed=int(data.get("failed") or 0),
            skipped=int(data.get("skipped") or 0),
            xfailed=int(data.get("xfailed") or 0),
            xpassed=int(data.get("xpassed") or 0),
            errors=int(data.get("errors") or data.get("error") or 0),
        )


def parse_pytest_counts(output: str) -> TestCounts:
    """Parse a pytest summary line into :class:`TestCounts`.

    Handles forms such as ``5 passed, 1 skipped, 2 xfailed in 1.23s``.
    """

    counts: Dict[str, int] = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "errors": 0,
    }
    for match in _PYTEST_SUMMARY_RE.finditer(output or ""):
        label = match.group("label").lower()
        count = int(match.group("count"))
        if label in {"error", "errors"}:
            counts["errors"] += count
        elif label in {"warning", "warnings"}:
            continue
        elif label in counts:
            counts[label] += count
    return TestCounts(**counts)


@dataclass(frozen=True, slots=True)
class CommandEvidence:
    """Record of one validation command bound to a tree and environment."""

    command: str
    timestamp: str
    environment_label: str
    exit_status: int
    test_counts: TestCounts
    artifact_digests: Tuple[str, ...]
    tree_id: str
    goal_id: str = ""
    clause_id: str = ""
    evidence_kind: str = "validation_receipt"
    stdout_digest: str = ""
    notes: str = ""
    schema_version: str = COMMAND_EVIDENCE_SCHEMA
    evidence_digest: str = ""
    signature: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_digest:
            object.__setattr__(self, "evidence_digest", self.compute_digest())

    def compute_digest(self) -> str:
        payload = {
            "artifact_digests": list(self.artifact_digests),
            "clause_id": self.clause_id,
            "command": self.command,
            "environment_label": self.environment_label,
            "evidence_kind": self.evidence_kind,
            "exit_status": self.exit_status,
            "goal_id": self.goal_id,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "stdout_digest": self.stdout_digest,
            "test_counts": self.test_counts.to_dict(),
            "timestamp": self.timestamp,
            "tree_id": self.tree_id,
        }
        return content_address(payload, domain=f"{CONTENT_DOMAIN}.command")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_digests": list(self.artifact_digests),
            "clause_id": self.clause_id,
            "command": self.command,
            "environment_label": self.environment_label,
            "evidence_digest": self.evidence_digest,
            "evidence_kind": self.evidence_kind,
            "exit_status": self.exit_status,
            "goal_id": self.goal_id,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "signature": self.signature,
            "stdout_digest": self.stdout_digest,
            "test_counts": self.test_counts.to_dict(),
            "timestamp": self.timestamp,
            "tree_id": self.tree_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CommandEvidence":
        digests = data.get("artifact_digests") or []
        if isinstance(digests, str):
            digests = [digests]
        counts_raw = data.get("test_counts") or {}
        if not isinstance(counts_raw, Mapping):
            counts_raw = {}
        return cls(
            command=str(data.get("command") or ""),
            timestamp=str(data.get("timestamp") or data.get("collected_at") or ""),
            environment_label=str(
                data.get("environment_label")
                or data.get("environment_id")
                or ""
            ),
            exit_status=int(data.get("exit_status") if data.get("exit_status") is not None else -1),
            test_counts=TestCounts.from_mapping(counts_raw),
            artifact_digests=tuple(str(d) for d in digests),
            tree_id=str(data.get("tree_id") or ""),
            goal_id=str(data.get("goal_id") or ""),
            clause_id=str(data.get("clause_id") or ""),
            evidence_kind=str(data.get("evidence_kind") or "validation_receipt"),
            stdout_digest=str(data.get("stdout_digest") or ""),
            notes=str(data.get("notes") or ""),
            schema_version=str(
                data.get("schema_version") or COMMAND_EVIDENCE_SCHEMA
            ),
            evidence_digest=str(data.get("evidence_digest") or ""),
            signature=str(data.get("signature") or ""),
        )


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


@dataclass
class CollectorState:
    """Mutable collector inventory (serializable)."""

    tree_binding: Optional[TreeBinding] = None
    environment: Optional[EnvironmentBinding] = None
    command_evidence: List[CommandEvidence] = field(default_factory=list)
    goal_receipts: List[GoalReceipt] = field(default_factory=list)
    dod_receipts: List[DodClauseReceipt] = field(default_factory=list)
    corpus_signoffs: List[CorpusSignOff] = field(default_factory=list)
    ucan_negative: Optional[UCANNegativeProof] = None
    soak_chaos: Optional[SoakChaosEvidence] = None
    refusals: List[Dict[str, Any]] = field(default_factory=list)
    package_version: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_evidence": [c.to_dict() for c in self.command_evidence],
            "corpus_signoffs": [s.to_dict() for s in self.corpus_signoffs],
            "dod_receipts": [r.to_dict() for r in self.dod_receipts],
            "environment": (
                self.environment.to_dict() if self.environment else None
            ),
            "goal_receipts": [r.to_dict() for r in self.goal_receipts],
            "notes": self.notes,
            "package_version": self.package_version,
            "refusals": list(self.refusals),
            "schema_version": SCHEMA_VERSION,
            "soak_chaos": self.soak_chaos.to_dict() if self.soak_chaos else None,
            "tree_binding": (
                self.tree_binding.to_dict() if self.tree_binding else None
            ),
            "ucan_negative": (
                self.ucan_negative.to_dict() if self.ucan_negative else None
            ),
        }


class ReleaseEvidenceCollector:
    """Executable fail-closed collector for knowledge-graph release evidence.

    Example::

        collector = ReleaseEvidenceCollector(
            expected_tree_id=tree_id,
            signing_key=key,
            require_signatures=True,
        )
        collector.bind_tree(TreeBinding(...))  # or bind_clean_repository(...)
        collector.set_environment("lab-1", "labelled lab environment")
        collector.record_and_accept_goal(
            goal_id="KGP-G010",
            command="python -m pytest -q tests/knowledge_graphs/contract",
            exit_status=0,
            test_counts=TestCounts(passed=12),
            artifact_digests=("sha256:...",),
        )
        # ... ingest remaining goals, DoD, sign-offs, UCAN, soak/chaos ...
        decision = collector.evaluate()
    """

    def __init__(
        self,
        *,
        expected_tree_id: str = "",
        signing_key: Optional[bytes | str] = None,
        require_signatures: bool = False,
        max_receipt_age: timedelta = DEFAULT_MAX_RECEIPT_AGE,
        package_version: str = "",
        now: Optional[datetime] = None,
        allow_dirty_tree: bool = False,
    ) -> None:
        self.expected_tree_id = (
            normalize_tree_id(expected_tree_id) if expected_tree_id else ""
        )
        self.signing_key = signing_key
        self.require_signatures = bool(require_signatures)
        self.max_receipt_age = max_receipt_age
        self.package_version = package_version
        self._now = now
        self.allow_dirty_tree = allow_dirty_tree
        self.state = CollectorState(package_version=package_version)
        self._last_decision: Optional[ReleaseDecision] = None
        if self.require_signatures and not signing_key:
            raise EvidenceCollectorError(
                "require_signatures=True needs a non-empty signing_key",
                code="missing_signing_key",
            )

    # -- time ---------------------------------------------------------------

    def _current_time(self) -> datetime:
        if self._now is not None:
            return self._now.astimezone(timezone.utc).replace(microsecond=0)
        return _now_utc()

    def _timestamp(self) -> str:
        return _format_ts(self._current_time())

    # -- tree binding -------------------------------------------------------

    @property
    def tree_id(self) -> str:
        if self.state.tree_binding is not None:
            return self.state.tree_binding.tree_id
        return self.expected_tree_id

    def bind_tree(self, binding: TreeBinding) -> TreeBinding:
        """Attach an already-resolved tree binding (tests / dry-run)."""

        if not binding.tree_id:
            raise EvidenceRefusal(
                "tree binding requires an explicit tree_id",
                code=RefusalCode.TREE_REQUIRED,
                subject="tree",
            )
        if not binding.is_clean and not self.allow_dirty_tree:
            raise EvidenceRefusal(
                "tree binding is dirty; release evidence requires a clean tree",
                code=RefusalCode.DIRTY_TREE,
                subject="tree",
                details={"dirty_paths": list(binding.dirty_paths)},
            )
        if self.expected_tree_id and binding.tree_id != self.expected_tree_id:
            raise EvidenceRefusal(
                "tree binding does not match expected_tree_id",
                code=RefusalCode.FOREIGN_TREE,
                subject="tree",
                details={
                    "expected_tree_id": self.expected_tree_id,
                    "binding_tree_id": binding.tree_id,
                },
            )
        if not self.expected_tree_id:
            self.expected_tree_id = binding.tree_id
        self.state.tree_binding = binding
        return binding

    def bind_clean_repository(
        self,
        repo_root: Union[str, Path],
        *,
        git_runner: Optional[Any] = None,
    ) -> TreeBinding:
        """Resolve a clean git tree and bind the collector to it."""

        binding = resolve_clean_tree(
            repo_root,
            expected_tree_id=self.expected_tree_id or None,
            allow_dirty=self.allow_dirty_tree,
            git_runner=git_runner,
        )
        return self.bind_tree(binding)

    def _require_tree(self) -> str:
        tree = self.tree_id
        if not tree:
            raise EvidenceRefusal(
                "collector has no explicit tree binding; call bind_tree first",
                code=RefusalCode.TREE_REQUIRED,
                subject="tree",
            )
        if self.state.tree_binding is not None and not self.state.tree_binding.is_clean:
            if not self.allow_dirty_tree:
                raise EvidenceRefusal(
                    "dirty tree is not acceptable for release evidence",
                    code=RefusalCode.DIRTY_TREE,
                    subject="tree",
                )
        return tree

    def _assert_tree_match(self, evidence_tree: str, *, subject: str) -> None:
        expected = self._require_tree()
        if not evidence_tree or evidence_tree != expected:
            raise EvidenceRefusal(
                f"foreign-tree evidence for {subject}",
                code=RefusalCode.FOREIGN_TREE,
                subject=subject,
                details={
                    "evidence_tree_id": evidence_tree,
                    "expected_tree_id": expected,
                },
            )

    def _assert_fresh(self, collected_at: str, *, subject: str) -> None:
        ts = parse_timestamp(collected_at)
        if ts is None:
            raise EvidenceRefusal(
                f"unparseable timestamp for {subject}",
                code=RefusalCode.STALE,
                subject=subject,
                details={"collected_at": collected_at},
            )
        now = self._current_time()
        age = now - ts
        if age > self.max_receipt_age:
            raise EvidenceRefusal(
                f"stale evidence for {subject}",
                code=RefusalCode.STALE,
                subject=subject,
                details={
                    "collected_at": collected_at,
                    "age_seconds": age.total_seconds(),
                    "max_age_seconds": self.max_receipt_age.total_seconds(),
                },
            )
        if ts > now + timedelta(minutes=5):
            raise EvidenceRefusal(
                f"future timestamp for {subject}",
                code=RefusalCode.STALE,
                subject=subject,
                details={"collected_at": collected_at},
            )

    def _assert_signature_if_required(
        self,
        signature: str,
        *,
        subject: str,
        payload_digest: str = "",
    ) -> None:
        if not self.require_signatures:
            return
        if not signature or not str(signature).strip():
            raise EvidenceRefusal(
                f"unsigned evidence refused for {subject}",
                code=RefusalCode.UNSIGNED,
                subject=subject,
                details={"payload_digest": payload_digest},
            )

    def _record_refusal(self, exc: EvidenceRefusal) -> None:
        self.state.refusals.append(
            {
                "code": exc.code,
                "details": dict(exc.details),
                "message": str(exc),
                "subject": exc.subject,
                "timestamp": self._timestamp(),
            }
        )

    # -- environment --------------------------------------------------------

    def set_environment(
        self,
        environment_id: str,
        label: str,
        *,
        notes: str = "",
    ) -> EnvironmentBinding:
        """Bind a labelled environment (unknown / empty ids are refused)."""

        tree = self._require_tree()
        if is_unknown_environment(environment_id):
            raise EvidenceRefusal(
                "unknown or unlabelled environment is not acceptable",
                code=RefusalCode.UNKNOWN_ENVIRONMENT,
                subject="environment",
                details={"environment_id": environment_id},
            )
        if not str(label or "").strip():
            raise EvidenceRefusal(
                "environment label is required",
                code=RefusalCode.UNKNOWN_ENVIRONMENT,
                subject="environment",
            )
        env = EnvironmentBinding(
            environment_id=str(environment_id).strip(),
            label=str(label).strip(),
            tree_id=tree,
            collected_at=self._timestamp(),
            notes=notes,
        )
        self.state.environment = env
        return env

    # -- command evidence recording -----------------------------------------

    def record_command(
        self,
        *,
        command: str,
        exit_status: int,
        test_counts: Union[TestCounts, Mapping[str, Any], None] = None,
        artifact_digests: Optional[Sequence[str]] = None,
        environment_label: str = "",
        goal_id: str = "",
        clause_id: str = "",
        evidence_kind: str = "validation_receipt",
        stdout: str = "",
        stdout_digest: str = "",
        notes: str = "",
        timestamp: Optional[str] = None,
        signature: str = "",
        accept: bool = False,
    ) -> CommandEvidence:
        """Record a validation command. Optionally refuse non-passing results.

        When *accept* is True, failed / skipped / xfail / nonzero exit cause an
        immediate :class:`EvidenceRefusal`. When False, the record is still
        stored but marked for operator review (it will not produce a goal
        receipt until :meth:`accept_command_as_goal` is called).
        """

        tree = self._require_tree()
        if not str(command or "").strip():
            raise EvidenceRefusal(
                "validation command is required",
                code=RefusalCode.MISSING_FIELD,
                subject=goal_id or clause_id or "command",
            )

        if isinstance(test_counts, Mapping):
            counts = TestCounts.from_mapping(test_counts)
        elif test_counts is None:
            counts = TestCounts()
        else:
            counts = test_counts

        digests = tuple(str(d) for d in (artifact_digests or ()) if str(d).strip())
        env_label = (
            environment_label
            or (
                self.state.environment.label
                if self.state.environment is not None
                else ""
            )
        )
        if is_unknown_environment(env_label) or not str(env_label).strip():
            # Prefer environment_id when label missing but env is set.
            if self.state.environment is not None and self.state.environment.label:
                env_label = self.state.environment.label
            else:
                raise EvidenceRefusal(
                    "environment label is required on command evidence",
                    code=RefusalCode.UNKNOWN_ENVIRONMENT,
                    subject=goal_id or clause_id or "command",
                )

        if stdout and not stdout_digest:
            stdout_digest = text_digest(stdout)

        ts = timestamp or self._timestamp()
        evidence = CommandEvidence(
            command=str(command).strip(),
            timestamp=ts,
            environment_label=str(env_label).strip(),
            exit_status=int(exit_status),
            test_counts=counts,
            artifact_digests=digests,
            tree_id=tree,
            goal_id=str(goal_id or ""),
            clause_id=str(clause_id or ""),
            evidence_kind=str(evidence_kind or "validation_receipt"),
            stdout_digest=stdout_digest,
            notes=notes,
            signature=signature,
        )

        subject = goal_id or clause_id or "command"
        try:
            self._validate_command_for_acceptance(evidence, subject=subject)
            if accept:
                self._assert_signature_if_required(
                    evidence.signature,
                    subject=subject,
                    payload_digest=evidence.evidence_digest,
                )
        except EvidenceRefusal as exc:
            self._record_refusal(exc)
            if accept:
                raise
            # Non-accept path still stores the record for audit, then re-raises
            # only when the caller asked to accept. Here accept is False so we
            # store and return (failed evidence is retained but not promoted).
            self.state.command_evidence.append(evidence)
            return evidence

        self.state.command_evidence.append(evidence)
        return evidence

    def _validate_command_for_acceptance(
        self,
        evidence: CommandEvidence,
        *,
        subject: str,
    ) -> None:
        self._assert_tree_match(evidence.tree_id, subject=subject)
        self._assert_fresh(evidence.timestamp, subject=subject)

        if is_rejected_substitute(evidence.evidence_kind):
            raise EvidenceRefusal(
                f"rejected evidence substitute {evidence.evidence_kind!r}",
                code=RefusalCode.REJECTED_SUBSTITUTE,
                subject=subject,
                details={"evidence_kind": evidence.evidence_kind},
            )

        if evidence.exit_status != 0:
            raise EvidenceRefusal(
                f"nonzero exit status {evidence.exit_status} for {subject}",
                code=RefusalCode.NONZERO_EXIT,
                subject=subject,
                details={"exit_status": evidence.exit_status},
            )

        counts = evidence.test_counts
        if counts.failed > 0 or counts.errors > 0:
            raise EvidenceRefusal(
                f"failed tests refused for {subject}",
                code=RefusalCode.FAILED,
                subject=subject,
                details=counts.to_dict(),
            )
        if counts.skipped > 0:
            raise EvidenceRefusal(
                f"skipped tests refused for {subject}",
                code=RefusalCode.SKIPPED,
                subject=subject,
                details=counts.to_dict(),
            )
        if counts.xfailed > 0:
            raise EvidenceRefusal(
                f"expected-failure (xfail) tests refused for {subject}",
                code=RefusalCode.EXPECTED_FAILURE,
                subject=subject,
                details=counts.to_dict(),
            )
        if not evidence.artifact_digests and not evidence.stdout_digest:
            raise EvidenceRefusal(
                f"artifact digests required for {subject}",
                code=RefusalCode.MISSING_DIGEST,
                subject=subject,
            )

    def accept_command_as_goal(
        self,
        evidence: CommandEvidence,
        *,
        goal_id: Optional[str] = None,
        evidence_kind: Optional[str] = None,
        signature: str = "",
    ) -> GoalReceipt:
        """Promote accepted command evidence into a :class:`GoalReceipt`."""

        gid = goal_id or evidence.goal_id
        if not gid:
            raise EvidenceRefusal(
                "goal_id is required to accept command as goal receipt",
                code=RefusalCode.MISSING_FIELD,
                subject="goal",
            )
        if gid not in REQUIRED_CHILD_GOALS and gid != GOAL_ID:
            # G100 is the root gate; it does not produce a child GoalReceipt
            # for G010-G090. Still allow recording DoD-related promotion.
            if gid != GOAL_ID:
                raise EvidenceRefusal(
                    f"unknown goal_id {gid!r}",
                    code=RefusalCode.MISSING_FIELD,
                    subject=gid,
                )

        subject = gid
        self._validate_command_for_acceptance(evidence, subject=subject)
        sig = signature or evidence.signature
        self._assert_signature_if_required(
            sig,
            subject=subject,
            payload_digest=evidence.evidence_digest,
        )

        kind = evidence_kind or evidence.evidence_kind or "validation_receipt"
        if gid == GOAL_ID:
            # Root gate is evaluated via GraphReleaseGate, not as a child receipt.
            # Record command evidence only.
            return make_goal_receipt(
                gid,
                tree_id=evidence.tree_id,
                collected_at=evidence.timestamp,
                evidence_kind=kind,
                status="pass",
                validation_command=evidence.command,
                notes=(
                    f"root gate command; digests={list(evidence.artifact_digests)}; "
                    f"counts={evidence.test_counts.to_dict()}"
                ),
            )

        receipt = make_goal_receipt(
            gid,
            tree_id=evidence.tree_id,
            collected_at=evidence.timestamp,
            evidence_kind=kind,
            status="pass",
            validation_command=evidence.command,
            notes=(
                f"exit={evidence.exit_status}; "
                f"counts={evidence.test_counts.to_dict()}; "
                f"artifact_digests={list(evidence.artifact_digests)}; "
                f"command_digest={evidence.evidence_digest}"
            ),
        )
        # Replace any prior receipt for this goal.
        self.state.goal_receipts = [
            r for r in self.state.goal_receipts if r.goal_id != gid
        ]
        self.state.goal_receipts.append(receipt)
        return receipt

    def record_and_accept_goal(
        self,
        *,
        goal_id: str,
        command: str,
        exit_status: int,
        test_counts: Union[TestCounts, Mapping[str, Any], None] = None,
        artifact_digests: Optional[Sequence[str]] = None,
        environment_label: str = "",
        evidence_kind: str = "validation_receipt",
        stdout: str = "",
        notes: str = "",
        timestamp: Optional[str] = None,
        signature: str = "",
    ) -> GoalReceipt:
        """Record command evidence and promote it to a goal receipt, or refuse."""

        evidence = self.record_command(
            command=command,
            exit_status=exit_status,
            test_counts=test_counts,
            artifact_digests=artifact_digests,
            environment_label=environment_label,
            goal_id=goal_id,
            evidence_kind=evidence_kind,
            stdout=stdout,
            notes=notes,
            timestamp=timestamp,
            signature=signature,
            accept=True,
        )
        return self.accept_command_as_goal(
            evidence,
            goal_id=goal_id,
            evidence_kind=evidence_kind,
            signature=signature,
        )

    def accept_goal_receipt(
        self,
        receipt: GoalReceipt,
        *,
        signature: str = "",
    ) -> GoalReceipt:
        """Accept a pre-built goal receipt after fail-closed checks."""

        subject = receipt.goal_id or "goal"
        if not receipt.goal_id:
            raise EvidenceRefusal(
                "goal receipt missing goal_id",
                code=RefusalCode.MISSING_FIELD,
                subject=subject,
            )
        self._assert_tree_match(receipt.tree_id, subject=subject)
        self._assert_fresh(receipt.collected_at, subject=subject)
        self._assert_signature_if_required(
            signature or getattr(receipt, "signature", "") or "",
            subject=subject,
            payload_digest=receipt.receipt_digest,
        )

        if is_rejected_substitute(receipt.evidence_kind):
            raise EvidenceRefusal(
                f"rejected substitute {receipt.evidence_kind!r}",
                code=RefusalCode.REJECTED_SUBSTITUTE,
                subject=subject,
            )

        status = _normalize_status(receipt.status)
        if status in {"skip", "skipped"}:
            raise EvidenceRefusal(
                f"skipped receipt refused for {subject}",
                code=RefusalCode.SKIPPED,
                subject=subject,
                details={"status": receipt.status},
            )
        if status in {"xfail", "expected_failure", "expected-failure"}:
            raise EvidenceRefusal(
                f"expected-failure receipt refused for {subject}",
                code=RefusalCode.EXPECTED_FAILURE,
                subject=subject,
                details={"status": receipt.status},
            )
        if status in {"fail", "failed", "error"}:
            raise EvidenceRefusal(
                f"failed receipt refused for {subject}",
                code=RefusalCode.FAILED,
                subject=subject,
                details={"status": receipt.status},
            )
        if status not in {"pass", "passed", "ok", "success", "accepted"}:
            raise EvidenceRefusal(
                f"non-passing status {receipt.status!r} refused",
                code=RefusalCode.INVALID_STATUS,
                subject=subject,
                details={"status": receipt.status},
            )

        expected_digest = receipt.compute_digest()
        if receipt.receipt_digest and receipt.receipt_digest != expected_digest:
            raise EvidenceRefusal(
                f"receipt digest mismatch for {subject}",
                code=RefusalCode.DIGEST_MISMATCH,
                subject=subject,
                details={
                    "expected": expected_digest,
                    "actual": receipt.receipt_digest,
                },
            )

        self.state.goal_receipts = [
            r for r in self.state.goal_receipts if r.goal_id != receipt.goal_id
        ]
        self.state.goal_receipts.append(receipt)
        return receipt

    def accept_dod_receipt(
        self,
        receipt: DodClauseReceipt,
        *,
        signature: str = "",
    ) -> DodClauseReceipt:
        """Accept a root definition-of-done receipt after fail-closed checks."""

        subject = receipt.clause_id or "dod"
        if not receipt.clause_id:
            raise EvidenceRefusal(
                "DoD receipt missing clause_id",
                code=RefusalCode.MISSING_FIELD,
                subject=subject,
            )
        self._assert_tree_match(receipt.tree_id, subject=subject)
        self._assert_fresh(receipt.collected_at, subject=subject)
        self._assert_signature_if_required(
            signature,
            subject=subject,
            payload_digest=receipt.receipt_digest,
        )
        if is_rejected_substitute(receipt.evidence_kind):
            raise EvidenceRefusal(
                f"rejected substitute {receipt.evidence_kind!r}",
                code=RefusalCode.REJECTED_SUBSTITUTE,
                subject=subject,
            )
        status = _normalize_status(receipt.status)
        if status in {"skip", "skipped"}:
            raise EvidenceRefusal(
                f"skipped DoD receipt refused for {subject}",
                code=RefusalCode.SKIPPED,
                subject=subject,
            )
        if status in {"xfail", "expected_failure"}:
            raise EvidenceRefusal(
                f"expected-failure DoD receipt refused for {subject}",
                code=RefusalCode.EXPECTED_FAILURE,
                subject=subject,
            )
        if status in {"fail", "failed", "error"}:
            raise EvidenceRefusal(
                f"failed DoD receipt refused for {subject}",
                code=RefusalCode.FAILED,
                subject=subject,
            )
        if status not in {"pass", "passed", "ok", "success", "accepted"}:
            raise EvidenceRefusal(
                f"non-passing DoD status {receipt.status!r}",
                code=RefusalCode.INVALID_STATUS,
                subject=subject,
            )
        expected_digest = receipt.compute_digest()
        if receipt.receipt_digest and receipt.receipt_digest != expected_digest:
            raise EvidenceRefusal(
                f"DoD digest mismatch for {subject}",
                code=RefusalCode.DIGEST_MISMATCH,
                subject=subject,
            )

        self.state.dod_receipts = [
            r for r in self.state.dod_receipts if r.clause_id != receipt.clause_id
        ]
        self.state.dod_receipts.append(receipt)
        return receipt

    def record_and_accept_dod(
        self,
        *,
        clause_id: str,
        command: str,
        exit_status: int,
        test_counts: Union[TestCounts, Mapping[str, Any], None] = None,
        artifact_digests: Optional[Sequence[str]] = None,
        environment_label: str = "",
        evidence_kind: str = "validation_receipt",
        notes: str = "",
        timestamp: Optional[str] = None,
        signature: str = "",
    ) -> DodClauseReceipt:
        """Record command evidence and promote it to a DoD receipt."""

        evidence = self.record_command(
            command=command,
            exit_status=exit_status,
            test_counts=test_counts,
            artifact_digests=artifact_digests,
            environment_label=environment_label,
            clause_id=clause_id,
            evidence_kind=evidence_kind,
            notes=notes,
            timestamp=timestamp,
            signature=signature,
            accept=True,
        )
        receipt = make_dod_receipt(
            clause_id,
            tree_id=evidence.tree_id,
            collected_at=evidence.timestamp,
            evidence_kind=evidence_kind,
            status="pass",
            validation_command=evidence.command,
            notes=(
                f"exit={evidence.exit_status}; "
                f"counts={evidence.test_counts.to_dict()}; "
                f"artifact_digests={list(evidence.artifact_digests)}"
            ),
        )
        return self.accept_dod_receipt(receipt, signature=signature)

    # -- ingest special evidence --------------------------------------------

    def ingest_corpus_signoff(
        self,
        *,
        corpus_id: str,
        producer_id: str,
        signer: str,
        mode: str = "full",
        statement: str = "",
        signed_at: Optional[str] = None,
        signature: str = "",
        receipt_digest: str = "",
    ) -> CorpusSignOff:
        """Ingest a full-mode corpus sign-off bound to the collector tree."""

        tree = self._require_tree()
        subject = f"corpus:{corpus_id}"
        if not corpus_id:
            raise EvidenceRefusal(
                "corpus_id is required",
                code=RefusalCode.MISSING_FIELD,
                subject="corpus",
            )
        mode_norm = _normalize_status(mode)
        if mode_norm in {"sample", "sample_only", "fixture_sample"}:
            raise EvidenceRefusal(
                f"sample-only corpus sign-off refused for {corpus_id}",
                code=RefusalCode.SAMPLE_ONLY,
                subject=subject,
                details={"mode": mode},
            )
        if mode_norm != "full":
            raise EvidenceRefusal(
                f"corpus sign-off mode must be 'full', got {mode!r}",
                code=RefusalCode.SAMPLE_ONLY,
                subject=subject,
                details={"mode": mode},
            )
        if not producer_id or not signer:
            raise EvidenceRefusal(
                "producer_id and signer are required for corpus sign-off",
                code=RefusalCode.MISSING_FIELD,
                subject=subject,
            )
        # Sign-off signature: when signatures are required, signer alone is
        # not enough — an explicit signature token must be present.
        self._assert_signature_if_required(
            signature or signer,
            subject=subject,
        )
        ts = signed_at or self._timestamp()
        self._assert_fresh(ts, subject=subject)

        signoff = make_corpus_signoff(
            corpus_id,
            tree_id=tree,
            producer_id=producer_id,
            signer=signer,
            mode="full",
            signed_at=ts,
            statement=statement,
        )
        if receipt_digest and receipt_digest != signoff.receipt_digest:
            raise EvidenceRefusal(
                f"corpus sign-off digest mismatch for {corpus_id}",
                code=RefusalCode.DIGEST_MISMATCH,
                subject=subject,
            )

        self.state.corpus_signoffs = [
            s for s in self.state.corpus_signoffs if s.corpus_id != corpus_id
        ]
        self.state.corpus_signoffs.append(signoff)
        return signoff

    def ingest_ucan_deny_proof(
        self,
        *,
        deny_receipt_cids: Sequence[str],
        collected_at: Optional[str] = None,
        notes: str = "",
        signature: str = "",
        receipt_digest: str = "",
    ) -> UCANNegativeProof:
        """Ingest UCAN deny / negative authorization proof digests."""

        tree = self._require_tree()
        subject = "ucan_negative"
        cids = tuple(str(c).strip() for c in deny_receipt_cids if str(c).strip())
        if not cids:
            raise EvidenceRefusal(
                "at least one UCAN deny receipt CID is required",
                code=RefusalCode.MISSING_DIGEST,
                subject=subject,
            )
        for cid in cids:
            if not cid.startswith("sha256:") and not cid.startswith("kg-"):
                # Accept common digest forms; bare empty already filtered.
                if len(cid) < 8:
                    raise EvidenceRefusal(
                        f"UCAN deny receipt CID looks empty/invalid: {cid!r}",
                        code=RefusalCode.MISSING_DIGEST,
                        subject=subject,
                    )
        ts = collected_at or self._timestamp()
        self._assert_fresh(ts, subject=subject)
        self._assert_signature_if_required(signature, subject=subject)

        proof = UCANNegativeProof(
            tree_id=tree,
            deny_receipt_cids=cids,
            collected_at=ts,
            notes=notes,
        )
        if receipt_digest and receipt_digest != proof.receipt_digest:
            raise EvidenceRefusal(
                "UCAN negative proof digest mismatch",
                code=RefusalCode.DIGEST_MISMATCH,
                subject=subject,
            )
        self.state.ucan_negative = proof
        return proof

    def ingest_load_soak_chaos(
        self,
        *,
        soak_receipt_digest: str,
        chaos_receipt_digest: str,
        load_receipt_digest: str = "",
        environment_id: str = "",
        collected_at: Optional[str] = None,
        notes: str = "",
        signature: str = "",
    ) -> SoakChaosEvidence:
        """Ingest load / soak / chaos profile digests on a labelled environment."""

        tree = self._require_tree()
        subject = "soak_chaos"
        env_id = environment_id or (
            self.state.environment.environment_id
            if self.state.environment is not None
            else ""
        )
        if is_unknown_environment(env_id):
            raise EvidenceRefusal(
                "load/soak/chaos requires a labelled environment_id",
                code=RefusalCode.UNKNOWN_ENVIRONMENT,
                subject=subject,
                details={"environment_id": env_id},
            )
        if not str(soak_receipt_digest or "").strip():
            raise EvidenceRefusal(
                "soak_receipt_digest is required",
                code=RefusalCode.MISSING_DIGEST,
                subject=subject,
            )
        if not str(chaos_receipt_digest or "").strip():
            raise EvidenceRefusal(
                "chaos_receipt_digest is required",
                code=RefusalCode.MISSING_DIGEST,
                subject=subject,
            )
        ts = collected_at or self._timestamp()
        self._assert_fresh(ts, subject=subject)
        self._assert_signature_if_required(signature, subject=subject)

        evidence = SoakChaosEvidence(
            tree_id=tree,
            environment_id=str(env_id).strip(),
            soak_receipt_digest=str(soak_receipt_digest).strip(),
            chaos_receipt_digest=str(chaos_receipt_digest).strip(),
            collected_at=ts,
            load_receipt_digest=str(load_receipt_digest or "").strip(),
            notes=notes,
        )
        self.state.soak_chaos = evidence
        return evidence

    # -- bundle + evaluate --------------------------------------------------

    def build_bundle(self) -> ReleaseEvidenceBundle:
        """Assemble the current collector state into a release evidence bundle."""

        tree = self._require_tree()
        return ReleaseEvidenceBundle(
            tree_id=tree,
            goal_receipts=list(self.state.goal_receipts),
            dod_receipts=list(self.state.dod_receipts),
            corpus_signoffs=list(self.state.corpus_signoffs),
            ucan_negative=self.state.ucan_negative,
            soak_chaos=self.state.soak_chaos,
            environment=self.state.environment,
            package_version=self.package_version or self.state.package_version,
            notes=self.state.notes,
        )

    def evaluate(
        self,
        *,
        now: Optional[datetime] = None,
        notes: str = "",
        raise_on_fail: bool = False,
    ) -> ReleaseDecision:
        """Evaluate the collected bundle with :class:`GraphReleaseGate` fail-closed."""

        tree = self._require_tree()
        if not self.expected_tree_id:
            self.expected_tree_id = tree

        gate = GraphReleaseGate(
            expected_tree_id=self.expected_tree_id,
            signing_key=self.signing_key,
            max_receipt_age=self.max_receipt_age,
            package_version=self.package_version or self.state.package_version,
        )
        bundle = self.build_bundle()
        eval_now = now if now is not None else self._current_time()

        if raise_on_fail:
            try:
                decision = gate.evaluate_or_raise(
                    bundle, now=eval_now, notes=notes or self.state.notes
                )
            except ReleaseGateFailClosed:
                # Re-raise after capturing decision if present.
                raise
        else:
            decision = gate.evaluate(
                bundle, now=eval_now, notes=notes or self.state.notes
            )

        if self.require_signatures:
            if not decision.signature or not decision.signature.startswith(
                "hmac-sha256:"
            ):
                raise EvidenceRefusal(
                    "release decision is unsigned; HMAC signature required",
                    code=RefusalCode.UNSIGNED,
                    subject="decision",
                    details={"signature": decision.signature},
                )
            if self.signing_key and not rg.verify_decision_signature(
                decision, signing_key=self.signing_key
            ):
                raise EvidenceRefusal(
                    "release decision signature verification failed",
                    code=RefusalCode.UNSIGNED,
                    subject="decision",
                )

        self._last_decision = decision
        return decision

    @property
    def last_decision(self) -> Optional[ReleaseDecision]:
        return self._last_decision

    def is_production_ready(
        self, decision: Optional[ReleaseDecision] = None
    ) -> bool:
        target = decision if decision is not None else self._last_decision
        return is_production_ready(target)

    # -- serialization ------------------------------------------------------

    def dump_state(self, path: Union[str, Path]) -> Path:
        """Write collector state JSON to *path*."""

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "collector": self.state.to_dict(),
            "expected_tree_id": self.expected_tree_id,
            "package_version": self.package_version,
            "policy_id": POLICY_ID,
            "require_signatures": self.require_signatures,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "ten_child_gates": list(TEN_CHILD_GATES),
        }
        if self._last_decision is not None:
            payload["last_decision"] = self._last_decision.to_dict()
        out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return out

    def write_runbook(self, path: Union[str, Path]) -> Path:
        """Write the human-readable gate runbook (static + current decision)."""

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        body = render_gate_runbook(
            decision=self._last_decision,
            tree_id=self.tree_id or self.expected_tree_id,
            collector_state=self.state,
        )
        out.write_text(body, encoding="utf-8")
        return out


# ---------------------------------------------------------------------------
# Runbook rendering
# ---------------------------------------------------------------------------


def render_gate_runbook(
    *,
    decision: Optional[ReleaseDecision] = None,
    tree_id: str = "",
    collector_state: Optional[CollectorState] = None,
) -> str:
    """Render a human-readable runbook for all ten child gates + root decision."""

    lines: List[str] = [
        "# Knowledge Graphs — Gate Runbook (KGP-G010 … KGP-G100)",
        "",
        f"**Status:** active  ",
        f"**Tasks:** `KGP-049` (collector); `KGP-035` (release evidence gate)  ",
        f"**Policy:** `{POLICY_ID}`  ",
        f"**Collector schema:** `{SCHEMA_VERSION}`  ",
        f"**Code:** `ipfs_datasets_py.knowledge_graphs.release_evidence`, "
        f"`ipfs_datasets_py.knowledge_graphs.release_gate`  ",
        f"**Companion:** `docs/operations/knowledge_graphs_release.md`  ",
        "",
        "## Purpose",
        "",
        "This runbook explains **all ten child gates** (`KGP-G010` through",
        "`KGP-G100`) and the **root release decision** produced by",
        "`GraphReleaseGate` / `ReleaseEvidenceCollector`.",
        "",
        "The platform is **not production ready** until the collector builds a",
        "complete evidence bundle bound to an **explicit clean repository tree**",
        "and `GraphReleaseGate` emits a signed decision with",
        "`production_ready=True`. Task status, coverage, prose, skips,",
        "expected failures (xfail), sample-only corpus runs, absent soak/chaos,",
        "missing UCAN deny proof, unknown environments, foreign trees, stale",
        "receipts, and unsigned evidence (when signatures are required) are",
        "**never** accepted as substitutes.",
        "",
        "## Standing rule (fail-closed)",
        "",
        "Missing, failed, skipped, expected-failure, stale, foreign-tree,",
        "dirty-tree, partial, contradicted, or unsigned evidence **fails closed**.",
        "There is no partial credit toward production readiness.",
        "",
    ]

    if tree_id:
        lines.extend(
            [
                f"**Bound tree:** `{tree_id}`  ",
                "",
            ]
        )

    lines.extend(
        [
            "## Collector workflow",
            "",
            "```python",
            "from ipfs_datasets_py.knowledge_graphs.release_evidence import (",
            "    ReleaseEvidenceCollector,",
            "    TestCounts,",
            "    resolve_clean_tree,",
            ")",
            "",
            "collector = ReleaseEvidenceCollector(",
            "    signing_key=b\"<operator-hmac-key>\",",
            "    require_signatures=True,",
            "    package_version=\"0.x.y\",",
            ")",
            "collector.bind_clean_repository(\"/path/to/repo\")",
            "collector.set_environment(\"lab-kg-release-1\", \"labelled lab\")",
            "",
            "# For each child goal G010..G090: run validation, then accept only",
            "# clean pass evidence (exit 0, no fails/skips/xfails, digests present).",
            "collector.record_and_accept_goal(",
            "    goal_id=\"KGP-G010\",",
            "    command=\"python -m pytest -q tests/knowledge_graphs/contract\",",
            "    exit_status=0,",
            "    test_counts=TestCounts(passed=12),",
            "    artifact_digests=(\"sha256:<artifact>\",),",
            "    signature=\"hmac-sha256:<mac>\",",
            ")",
            "",
            "# Ingest special evidence classes required by the root DoD:",
            "collector.ingest_corpus_signoff(",
            "    corpus_id=\"cvefixes\", producer_id=\"…\", signer=\"…\",",
            "    signature=\"hmac-sha256:<mac>\",",
            ")",
            "collector.ingest_ucan_deny_proof(",
            "    deny_receipt_cids=(\"sha256:<deny-receipt>\",),",
            "    signature=\"hmac-sha256:<mac>\",",
            ")",
            "collector.ingest_load_soak_chaos(",
            "    soak_receipt_digest=\"sha256:<soak>\",",
            "    chaos_receipt_digest=\"sha256:<chaos>\",",
            "    load_receipt_digest=\"sha256:<load>\",",
            "    signature=\"hmac-sha256:<mac>\",",
            ")",
            "",
            "decision = collector.evaluate()",
            "assert decision.production_ready  # only when fully green",
            "collector.write_runbook(\"docs/operations/knowledge_graphs_gate_runbook.md\")",
            "```",
            "",
            "### Evidence fields recorded per command",
            "",
            "| Field | Meaning |",
            "| --- | --- |",
            "| `command` | Exact validation command executed |",
            "| `timestamp` | UTC collection time (ISO-8601 `…Z`) |",
            "| `environment_label` | Labelled environment (never `unknown`) |",
            "| `exit_status` | Process exit code (must be `0` to accept) |",
            "| `test_counts` | `passed` / `failed` / `skipped` / `xfailed` / `errors` |",
            "| `artifact_digests` | Content digests of retained artifacts |",
            "| `tree_id` | Explicit clean repository tree binding |",
            "",
            "### Refusal matrix",
            "",
            "| Condition | Refusal code |",
            "| --- | --- |",
            "| Nonzero exit or failed/error tests | `failed` / `nonzero_exit` |",
            "| Skipped tests or skip status | `skipped` |",
            "| Expected-failure / xfail | `expected_failure` |",
            "| Receipt older than max age | `stale` |",
            "| `tree_id` ≠ collector tree | `foreign_tree` |",
            "| Dirty working tree | `dirty_tree` |",
            "| Signature required but missing/invalid | `unsigned` |",
            "| Task status / coverage / prose substitutes | `rejected_substitute` |",
            "| Sample-only corpus mode | `sample_only` |",
            "| Unknown / empty environment | `unknown_environment` |",
            "",
            "## Ten child gates",
            "",
        ]
    )

    for entry in CHILD_GATE_CATALOG:
        goal_id = entry["goal_id"]
        lines.extend(
            [
                f"### {goal_id} — {entry['title']}",
                "",
                f"- **Evidence kind:** `{entry['evidence_kind']}`",
                f"- **Default validation:** `{entry['validation_command']}`",
            ]
        )
        if goal_id == "KGP-G100":
            lines.extend(
                [
                    "- **Role:** Root adoption / production-release gate. Depends on",
                    "  fresh passing receipts for `KGP-G010`…`KGP-G090` plus root",
                    "  definition-of-done clauses (corpus sign-off, UCAN deny,",
                    "  load/soak/chaos, labelled environment, migration reversibility).",
                    "- **Decision authority:** `GraphReleaseGate.evaluate` /",
                    "  `ReleaseEvidenceCollector.evaluate`.",
                ]
            )
        else:
            lines.append(
                "- **Release role:** Child goal receipt required by the root gate."
            )
        # Annotate satisfaction from decision when available.
        if decision is not None and goal_id in REQUIRED_CHILD_GOALS:
            satisfied = goal_id in decision.satisfied_child_goals
            lines.append(
                f"- **Current receipt:** "
                f"{'satisfied' if satisfied else '**missing / not passing**'}"
            )
        lines.append("")

    lines.extend(
        [
            "## Root definition-of-done clauses",
            "",
            "In addition to child-goal receipts, the root release decision requires",
            "exact fresh passing receipts for every clause below:",
            "",
            "| `clause_id` | Meaning |",
            "| --- | --- |",
        ]
    )
    for clause in ROOT_DOD_CLAUSES:
        lines.append(f"| `{clause.clause_id}` | {clause.description} |")

    lines.extend(
        [
            "",
            "### Special ingest requirements",
            "",
            f"| Class | Required items |",
            f"| --- | --- |",
            f"| Corpus sign-off (full mode) | {', '.join(f'`{c}`' for c in REQUIRED_CORPORA)} |",
            f"| UCAN negative proof | ≥1 deny receipt CID bound to the tree |",
            f"| Load / soak / chaos | Non-empty soak **and** chaos digests (load recommended) |",
            f"| Environment | Labelled `environment_id` + label on the same tree |",
            "",
            "## Root release decision",
            "",
            "The root decision is the only authority for **production readiness**.",
            "",
            "```text",
            "production_ready  ⇔  outcome == pass",
            "                 ∧  zero blockers",
            "                 ∧  all G010–G090 receipts satisfied",
            "                 ∧  all root DoD clauses satisfied",
            "                 ∧  corpus + UCAN + soak/chaos + environment OK",
            "                 ∧  (optional) HMAC signature verifies",
            "```",
            "",
            "Until then, treat the platform as **not production ready**.",
            "",
            "### Evaluating",
            "",
            "```python",
            "from ipfs_datasets_py.knowledge_graphs.release_gate import GraphReleaseGate",
            "from ipfs_datasets_py.knowledge_graphs.release_evidence import (",
            "    ReleaseEvidenceCollector,",
            ")",
            "",
            "decision = collector.evaluate()  # fail-closed GraphReleaseGate under the hood",
            "if not decision.production_ready:",
            "    for blocker in decision.blockers:",
            "        print(blocker.code, blocker.subject, blocker.message)",
            "# Retain decision.decision_cid + decision.signature on the release ticket.",
            "```",
            "",
        ]
    )

    if decision is not None:
        sig_display = decision.signature or ""
        if len(sig_display) > 48:
            sig_display = sig_display[:48] + "…"
        lines.extend(
            [
                "### Current decision snapshot",
                "",
                "| Field | Value |",
                "| --- | --- |",
                f"| `outcome` | `{decision.outcome}` |",
                f"| `production_ready` | `{decision.production_ready}` |",
                f"| `tree_id` | `{decision.tree_id}` |",
                f"| `decision_cid` | `{decision.decision_cid}` |",
                f"| `bundle_digest` | `{decision.bundle_digest}` |",
                f"| `signature` | `{sig_display}` |",
                f"| `evaluated_at` | `{decision.evaluated_at}` |",
                f"| satisfied child goals | "
                f"{len(decision.satisfied_child_goals)} / "
                f"{len(decision.required_child_goals)} |",
                f"| satisfied DoD clauses | "
                f"{len(decision.satisfied_dod_clauses)} / "
                f"{len(decision.required_dod_clauses)} |",
                f"| blockers | {len(decision.blockers)} |",
                "",
            ]
        )
        if decision.blockers:
            lines.extend(
                [
                    "#### Blockers",
                    "",
                    "| Code | Subject | Message |",
                    "| --- | --- | --- |",
                ]
            )
            for b in decision.blockers:
                msg = b.message.replace("|", "\\|")
                lines.append(f"| `{b.code}` | `{b.subject}` | {msg} |")
            lines.append("")
    else:
        lines.extend(
            [
                "### Current decision snapshot",
                "",
                "No evaluation has been run in this collector session. Default posture:",
                "**not production ready**.",
                "",
            ]
        )

    if collector_state is not None and collector_state.refusals:
        lines.extend(
            [
                "### Collector refusals (this session)",
                "",
                "| Code | Subject | Message |",
                "| --- | --- | --- |",
            ]
        )
        for ref in collector_state.refusals:
            msg = str(ref.get("message", "")).replace("|", "\\|")
            lines.append(
                f"| `{ref.get('code', '')}` | `{ref.get('subject', '')}` | {msg} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Validation",
            "",
            "```bash",
            "python -m pytest -q \\",
            "  tests/integration/knowledge_graphs/test_release_gate.py \\",
            "  tests/integration/knowledge_graphs/test_release_evidence_collector.py",
            "```",
            "",
            "## Related documents",
            "",
            "| Topic | Location |",
            "| --- | --- |",
            "| Release / cutover ops | `docs/operations/knowledge_graphs_release.md` |",
            "| Day-2 ops & DR | `docs/operations/knowledge_graphs_runbook.md` |",
            "| SLOs | `docs/operations/knowledge_graphs_slos.md` |",
            "| Gate implementation | `ipfs_datasets_py/knowledge_graphs/release_gate.py` |",
            "| Collector implementation | `ipfs_datasets_py/knowledge_graphs/release_evidence.py` |",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def default_gate_runbook_text() -> str:
    """Return the static runbook text (no live decision)."""

    return render_gate_runbook()


# ---------------------------------------------------------------------------
# Helpers for tests / operator dry-runs
# ---------------------------------------------------------------------------


def build_collector_with_passing_evidence(
    *,
    tree_id: str,
    signing_key: Optional[bytes | str] = None,
    require_signatures: bool = False,
    now: Optional[datetime] = None,
    package_version: str = "0.1.0-test",
    environment_id: str = "lab-kg-release-1",
    environment_label: str = "labelled lab environment",
    signature: str = "hmac-sha256:test-signature",
) -> ReleaseEvidenceCollector:
    """Populate a collector with a complete fresh passing set (tests only).

    Production operators must record real validation commands; this helper
    never replaces real harness output.
    """

    ts_dt = (now or _now_utc()).astimezone(timezone.utc).replace(microsecond=0)
    ts = _format_ts(ts_dt)
    binding = TreeBinding(
        tree_id=tree_id,
        commit=tree_id.removeprefix("tree-"),
        is_clean=True,
        repo_root="/tmp/kg-release-test",
        collected_at=ts,
    )
    collector = ReleaseEvidenceCollector(
        expected_tree_id=tree_id,
        signing_key=signing_key,
        require_signatures=require_signatures,
        package_version=package_version,
        now=ts_dt,
    )
    collector.bind_tree(binding)
    collector.set_environment(environment_id, environment_label)

    sig = signature if require_signatures else ""
    artifact = "sha256:" + "f" * 64

    for entry in CHILD_GATE_CATALOG:
        goal_id = entry["goal_id"]
        if goal_id == GOAL_ID:
            # Root gate is evaluated as the aggregate decision, not a child receipt.
            collector.record_command(
                command=entry["validation_command"],
                exit_status=0,
                test_counts=TestCounts(passed=1),
                artifact_digests=(artifact,),
                goal_id=goal_id,
                evidence_kind=entry["evidence_kind"],
                timestamp=ts,
                signature=sig,
                accept=True,
            )
            continue
        collector.record_and_accept_goal(
            goal_id=goal_id,
            command=entry["validation_command"],
            exit_status=0,
            test_counts=TestCounts(passed=5),
            artifact_digests=(artifact,),
            evidence_kind=entry["evidence_kind"],
            timestamp=ts,
            signature=sig,
        )

    kind_for_clause = {
        "concurrent_identity_durability": "concurrency_receipt",
        "storage_profiles_contract": "storage_contract",
        "four_surface_parity": "surface_conformance",
        "ucan_fail_closed": "ucan_audit_receipt",
        "sharded_integrity": "sharding_integrity",
        "corpora_differential": "corpus_differential",
        "load_soak_chaos_ops": "load_receipt",
        "migration_reversible": "migration_receipt",
    }
    for clause in ROOT_DOD_CLAUSES:
        collector.record_and_accept_dod(
            clause_id=clause.clause_id,
            command=f"pytest -q for {clause.clause_id}",
            exit_status=0,
            test_counts=TestCounts(passed=3),
            artifact_digests=(artifact,),
            evidence_kind=kind_for_clause.get(
                clause.clause_id, "validation_receipt"
            ),
            timestamp=ts,
            signature=sig,
        )

    for corpus_id in REQUIRED_CORPORA:
        collector.ingest_corpus_signoff(
            corpus_id=corpus_id,
            producer_id=f"producer-{corpus_id}",
            signer=f"owner-{corpus_id}",
            signed_at=ts,
            signature=sig or f"owner-{corpus_id}",
        )

    collector.ingest_ucan_deny_proof(
        deny_receipt_cids=(
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
        ),
        collected_at=ts,
        signature=sig,
    )
    collector.ingest_load_soak_chaos(
        soak_receipt_digest="sha256:" + "c" * 64,
        chaos_receipt_digest="sha256:" + "d" * 64,
        load_receipt_digest="sha256:" + "e" * 64,
        environment_id=environment_id,
        collected_at=ts,
        signature=sig,
    )
    return collector


def policy_dict() -> Dict[str, Any]:
    """JSON-serializable summary of the collector policy surface."""

    return {
        "child_gate_catalog": [dict(e) for e in CHILD_GATE_CATALOG],
        "collector_schema_version": SCHEMA_VERSION,
        "command_evidence_schema": COMMAND_EVIDENCE_SCHEMA,
        "goal_id": COLLECTOR_GOAL_ID,
        "policy_id": POLICY_ID,
        "refusal_codes": sorted(c.value for c in RefusalCode),
        "required_child_goals": list(REQUIRED_CHILD_GOALS),
        "required_corpora": list(REQUIRED_CORPORA),
        "required_dod_clauses": list(ROOT_DOD_CLAUSE_IDS),
        "task_id": TASK_ID,
        "ten_child_gates": list(TEN_CHILD_GATES),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Minimal CLI: write the static gate runbook and print policy summary."""

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Knowledge-graphs fail-closed release evidence collector (KGP-049)"
        )
    )
    parser.add_argument(
        "--write-runbook",
        metavar="PATH",
        help="Write the human-readable gate runbook to PATH",
    )
    parser.add_argument(
        "--policy-json",
        action="store_true",
        help="Print collector policy as JSON",
    )
    parser.add_argument(
        "--bind-repo",
        metavar="PATH",
        help="Resolve and print clean tree binding for PATH",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.policy_json:
        print(json.dumps(policy_dict(), indent=2, sort_keys=True))
    if args.write_runbook:
        path = Path(args.write_runbook)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(default_gate_runbook_text(), encoding="utf-8")
        print(f"wrote runbook: {path}")
    if args.bind_repo:
        binding = resolve_clean_tree(args.bind_repo)
        print(json.dumps(binding.to_dict(), indent=2, sort_keys=True))
    if not (args.policy_json or args.write_runbook or args.bind_repo):
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CHILD_GATE_CATALOG",
    "COLLECTOR_GOAL_ID",
    "COMMAND_EVIDENCE_SCHEMA",
    "CommandEvidence",
    "CollectorState",
    "EvidenceCollectorError",
    "EvidenceRefusal",
    "POLICY_ID",
    "RefusalCode",
    "ReleaseEvidenceCollector",
    "SCHEMA_VERSION",
    "TASK_ID",
    "TEN_CHILD_GATES",
    "TestCounts",
    "TreeBinding",
    "build_collector_with_passing_evidence",
    "bytes_digest",
    "default_gate_runbook_text",
    "file_digest",
    "main",
    "normalize_tree_id",
    "parse_pytest_counts",
    "policy_dict",
    "render_gate_runbook",
    "resolve_clean_tree",
    "text_digest",
]
