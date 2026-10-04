"""Small native conditional-evidence query qualification; no scaling claim.

Eight captured Python units are verified with Z3/CVC5 before measuring exact
queries, reverse dependencies, pagination and a fresh-process reopen. Historical
lookup replays recorded outputs; it does not attest those historical executions.
The current producer's process runner enforces wall time, not hard RSS/output
caps. Shared admission and this finite fixture do not change that limitation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
import traceback
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACCELERATE = ROOT.parent / "ipfs_accelerate"
SCHEMA = "codebase-evidence-query-benchmark@1"
VIEW = "repository:conditional-query-benchmark"
DB_CONFIG = {"threads": 1, "memory_limit": "64MB"}
SOURCE_FILES = (
    "benchmarks/bench_codebase_evidence_queries.py",
    "ipfs_datasets_py/duckdb_control/codebase_catalog.py",
    "ipfs_datasets_py/duckdb_control/codebase_verification_catalog.py",
    "ipfs_datasets_py/duckdb_control/codebase_verification_queries.py",
    "ipfs_datasets_py/duckdb_control/codebase_verification_projection.py",
    "ipfs_datasets_py/logic/software_contracts/codebase_ir.py",
    "ipfs_datasets_py/logic/software_contracts/codebase_resources.py",
    "ipfs_datasets_py/logic/software_contracts/codebase_verification.py",
    "ipfs_datasets_py/logic/software_contracts/codebase_applicability.py",
    "ipfs_datasets_py/logic/software_contracts/duckdb_ast_store.py",
    "ipfs_datasets_py/logic/software_contracts/duckdb_ingest.py",
    "ipfs_datasets_py/logic/software_contracts/cache.py",
    "ipfs_datasets_py/logic/software_contracts/content.py",
    "ipfs_datasets_py/logic/common/canonical_cache_key.py",
    "ipfs_datasets_py/logic/software_verification/pipeline.py",
    "ipfs_datasets_py/logic/software_verification/applicability.py",
    "ipfs_datasets_py/logic/backends/smt/differential.py",
    "ipfs_datasets_py/logic/backends/z3/compiler.py",
    "ipfs_datasets_py/logic/backends/cvc5/compiler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def progress(directory: Path, report: dict[str, Any], phase: str) -> None:
    """Retain each completed phase even if a later operation fails or is stopped."""
    report["active_phase"] = phase
    report["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    temporary = directory / "progress.json.tmp"
    with temporary.open("w") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, directory / "progress.json")


def source_pins() -> dict[str, str]:
    paths = [ROOT / relative for relative in SOURCE_FILES]
    paths += [ACCELERATE / "ipfs_accelerate_py/agent_supervisor/planning" / name
              for name in ("conditional_codebase_evidence.py", "structural_codebase_context.py")]
    # Missing declared producers are a qualification error, not an omitted pin.
    return {str(path): digest(path.read_bytes()) for path in paths}


@dataclass(frozen=True)
class FixtureUnit:
    path: str
    body_offset: int
    requested_offset: int
    domain_predicate: str
    expected_status: str

    @property
    def source(self) -> bytes:
        return f"def increment(n: int) -> int:\n    return n + {self.body_offset}\n".encode()

    def native(self):
        from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
        from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
        return (ContractSpec("increment", postconditions=(f"result == n + {self.requested_offset}",)),
                RequestedInputDomain("increment", (self.domain_predicate,), "domain:" + self.path))


def fixture_units() -> tuple[FixtureUnit, ...]:
    return tuple(FixtureUnit(f"unit_{number:02d}.py", number + 1,
                            number + 2 if number == 6 else number + 1,
                            "False" if number == 7 else "True",
                            "recorded_conditional_refuted" if number == 6 else
                            "recorded_conditional_vacuous" if number == 7 else "recorded_conditional_proved")
                 for number in range(8))


class ProcessAudit:
    """Audit actual Popen events without replacing any producer implementation."""

    def __init__(self) -> None:
        self.stage = "startup"
        self.only_git = False
        self.events: list[dict[str, Any]] = []
        self.counts: dict[str, int] = {}

    def observe(self, event: str, arguments: tuple[Any, ...]) -> None:
        if event != "subprocess.Popen":
            return
        executable, argv, cwd, _environment = arguments
        values = [os.fsdecode(item) for item in argv] if isinstance(argv, (list, tuple)) else [str(argv)]
        name = Path(os.fsdecode(executable)).name
        kind = ("version" if name in {"z3", "cvc5"} and any(
            item in {"--version", "-version"} for item in values) else
            "solver_query" if name in {"z3", "cvc5"} else "git" if name == "git" else "other")
        key = self.stage + ":" + kind
        self.counts[key] = self.counts.get(key, 0) + 1
        require(len(self.events) < 8192, "process audit retention exceeded")
        self.events.append({"stage": self.stage, "kind": kind, "executable": os.fsdecode(executable),
                            "argv": values, "cwd": None if cwd is None else os.fsdecode(cwd)})
        if self.only_git and name != "git":
            raise AssertionError(f"lookup attempted non-Git subprocess: {name}")

    @contextmanager
    def scope(self, name: str, *, only_git: bool = False):
        previous = self.stage, self.only_git
        self.stage, self.only_git = name, only_git
        try:
            yield
        finally:
            self.stage, self.only_git = previous


def open_index(directory: Path):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    cx = duckdb.connect(str(directory / "catalog.duckdb"), config=DB_CONFIG)
    store = DuckDBASTStore(connection=cx)
    artifacts = ImmutableCAS(directory / "artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    return index, CodebaseVerificationCatalog(index), cx


class Deadline:
    def __init__(self, seconds: float, operation_seconds: float) -> None:
        self.end = time.monotonic() + seconds
        self.operation_seconds = operation_seconds
        self.cancelled = threading.Event()
        self.timer = threading.Timer(seconds, self.cancelled.set)
        self.timer.daemon = True
        self.timer.start()

    def options(self) -> dict[str, Any]:
        remaining = self.end - time.monotonic()
        require(remaining > 0 and not self.cancelled.is_set(), "benchmark overall deadline exceeded")
        return {"timeout_seconds": min(remaining, self.operation_seconds),
                "admission_timeout_seconds": min(remaining, 30.0), "cancel_event": self.cancelled}

    def close(self) -> None:
        self.timer.cancel()


def own_leases(owner) -> list[dict[str, Any]]:
    return [item for item in owner.active_leases() if item["owner_pid"] == os.getpid()]


class Telemetry:
    """Sampled RSS/ancestry and shared pressure, not a containment mechanism."""

    def __init__(self, owner) -> None:
        self.owner = owner
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        import psutil
        process = psutil.Process()
        started = time.monotonic()
        while not self.stop_event.is_set():
            try:
                children = process.children(recursive=True)
                rows = []
                for child in children:
                    try:
                        rows.append({"pid": child.pid, "birth": child.create_time(),
                                     "rss_bytes": child.memory_info().rss, "threads": child.num_threads()})
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                state = self.owner.snapshot()
                observed_at = time.time()
                self.samples.append({"elapsed_seconds": time.monotonic() - started,
                    "observed_unix_time": observed_at,
                    "controller_rss_bytes": process.memory_info().rss,
                    "controller_threads": process.num_threads(), "descendants": rows,
                    "descendant_rss_bytes": sum(row["rss_bytes"] for row in rows),
                    "proof_backoff": state["proof_backoff"], "allocated": state["allocated"],
                    "proof_backoff_active": state["proof_backoff"].get("until", 0) > observed_at,
                    "active_lease_count": state["active_lease_count"],
                    "waiting_request_count": state["waiting_request_count"]})
            except Exception as error:
                self.errors.append(type(error).__name__ + ": " + str(error))
            if len(self.samples) >= 3600:
                self.errors.append("sample retention limit reached")
                return
            self.stop_event.wait(.5)

    def finish(self) -> dict[str, Any]:
        self.stop_event.set()
        self.thread.join(timeout=5)
        return {"sample_interval_seconds": .5, "samples": self.samples, "errors": self.errors,
                "sampler_stopped": not self.thread.is_alive(),
                "peak_controller_rss_bytes": max((row["controller_rss_bytes"] for row in self.samples), default=0),
                "peak_sampled_descendant_rss_bytes": max((row["descendant_rss_bytes"] for row in self.samples), default=0),
                "peak_sampled_descendant_processes": max((len(row["descendants"]) for row in self.samples), default=0),
                "scope": "sampled process tree; short-lived children may be missed; no aggregate hard memory limit"}


def assert_authority(projection) -> None:
    require(projection.verification.observed_live is False, "lookup promoted historical verification")
    require(all(value is False for name, value in projection.to_dict()["authority"].items()
                if name != "historical_conditional_evidence"), "projection promoted authority")
    if projection.applicability is not None:
        require(projection.applicability.observed_live is False, "lookup promoted historical applicability")


def traverse(catalog, repository, head, selector, deadline, *, page_size=3, cursor=None):
    rows, receipts, seen_cursors = [], [], set()
    inventory, epoch = None, None
    for _ in range(16):
        page = catalog.query_current(repository, expected_head=head, selector=selector,
                                     page_size=page_size, cursor=cursor, **deadline.options())
        receipt = page.to_dict()
        require("start_cursor" in receipt and receipt["start_cursor"] ==
                (None if cursor is None else cursor.to_dict()), "page does not bind its requested starting range")
        require(page.complete is (page.next_cursor is None), "terminal page/cursor mismatch")
        if inventory is None:
            inventory, epoch = page.inventory_cid, page.epoch
        require((page.inventory_cid, page.epoch) == (inventory, epoch), "page inventory drift")
        require(len(page.entries) <= page_size, "page result exceeded requested bound")
        for entry in page.entries:
            assert_authority(entry.projection)
            rows.append(entry.entry_id)
        receipts.append(receipt)
        if page.complete:
            require(rows == sorted(set(rows)), "page traversal repeated or reordered entries")
            return rows, receipts
        require(bool(page.entries), "nonterminal empty page")
        cursor = page.next_cursor
        marker = json.dumps(cursor.to_dict(), sort_keys=True)
        require(marker not in seen_cursors, "cursor cycle")
        seen_cursors.add(marker)
    raise AssertionError("page traversal exceeded finite fixture bound")


def authored_intent(unit: FixtureUnit, contract, domain):
    from ipfs_accelerate_py.agent_supervisor.planning import conditional_codebase_evidence as matcher
    from ipfs_datasets_py.logic.intent_ir.schema import (
        IntentIRDocument, IntentKind, IntentModality, IntentStatement, NodeGrounding,
        ReviewStatus, SourceRef, SourceSpan, StatementKind,
    )
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
    text = "Reviewed mathematical offset clause.\nReturn an exact Python int at runtime."
    end = text.index("\n")
    refs = tuple(SourceRef(ref_id="source:" + role, source_uri="intent:" + role,
        source_id="conditional:benchmark", source_revision="authored:1", content_sha256=digest(text.encode()),
        review_status=ReviewStatus.HUMAN_REVIEWED, span=SourceSpan(start, stop))
        for role, start, stop in (("math", 0, end), ("runtime", end + 1, len(text))))
    statements = (
        IntentStatement(statement_id="mathematical-goal", kind=StatementKind.GOAL,
            modality=IntentModality.REQUIRED, normalized_text=text[:end], source_ref_ids=(refs[0].ref_id,),
            predicate=matcher.PREDICATE,
            arguments=(unit.path, "increment", cid_for_structured(contract.to_dict()),
                       cid_for_structured(domain.to_dict()), matcher.PROFILE),
            grounding=NodeGrounding.GROUNDED, review_status=ReviewStatus.HUMAN_REVIEWED),
        IntentStatement(statement_id="runtime-goal", kind=StatementKind.GOAL,
            modality=IntentModality.REQUIRED, normalized_text=text[end + 1:], source_ref_ids=(refs[1].ref_id,),
            predicate="runtime_exact_integer", arguments=(unit.path, "increment"),
            grounding=NodeGrounding.GROUNDED, review_status=ReviewStatus.HUMAN_REVIEWED),
    )
    document = IntentIRDocument(document_id="intent:" + unit.path, title="Explicit mathematical request",
                               intent_kind=IntentKind.DECLARATIVE, sources=refs, statements=statements)
    document.validate()
    return text, document


def query_suite(catalog, index, directory, head, identities, audit, deadline, rounds):
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import CodebaseVerificationSelector as Selector
    from ipfs_accelerate_py.agent_supervisor.planning import conditional_codebase_evidence as matcher
    measurements, expected_entries, expected_pages = [], None, None
    repository = directory / "source"
    with audit.scope("lookup", only_git=True):
        for number in range(rounds):
            started = time.perf_counter()
            entries, pages = traverse(catalog, repository, head, Selector(), deadline)
            require(len(entries) == 8, "unexpected complete inventory size")
            expected_entries = entries if expected_entries is None else expected_entries
            require(entries == expected_entries, "unchanged query inventory changed")
            expected_pages = pages if expected_pages is None else expected_pages
            require(pages == expected_pages, "unchanged page receipts changed")
            row = {"round": number + 1, "all_pages_seconds": time.perf_counter() - started,
                   "pages": pages, "entry_ids": entries}
            started = time.perf_counter()
            reverse, receipts = traverse(catalog, repository, head,
                Selector(dependency_kind="snapshot", dependency_value=head.snapshot_cid), deadline)
            require(reverse == entries, "snapshot reverse index omitted an entry")
            row.update(snapshot_reverse_seconds=time.perf_counter() - started, snapshot_reverse_pages=receipts)
            exact_times, source_times = [], []
            for identity in identities:
                started = time.perf_counter()
                exact, receipts = traverse(catalog, repository, head,
                    Selector(path=identity["path"], contract_id=identity["contract_id"],
                        expected_contract_cid=identity["contract_cid"], verification_cid=identity["verification_cid"],
                        canonical_key_id=identity["key_id"], requested_domain_id=identity["domain_id"],
                        requested_domain_cid=identity["domain_cid"]), deadline)
                require(len(exact) == 1 and exact[0] in entries, "complete exact key did not select one entry")
                exact_times.append(time.perf_counter() - started)
                started = time.perf_counter()
                source, _ = traverse(catalog, repository, head,
                    Selector(dependency_kind="source", dependency_value=identity["source_cid"]), deadline)
                require(source == exact, "source reverse query selected another unit")
                source_times.append(time.perf_counter() - started)
            row.update(exact_key_seconds=exact_times, source_reverse_seconds=source_times)
            measurements.append(row)
        matcher_results = []
        for number in (0, 6, 7):
            unit, identity = fixture_units()[number], identities[number]
            contract, domain = unit.native()
            text, document = authored_intent(unit, contract, domain)
            started = time.perf_counter()
            result = matcher.match_conditional_codebase_intent(catalog=catalog, index=index,
                repository=repository, repository_id=head.repository_id, expected_head=head,
                intent_document=document, source_text=text, path=unit.path, contract=contract, domain=domain,
                statement_id="mathematical-goal", verification_cid=identity["verification_cid"],
                expected_key_id=identity["key_id"], **deadline.options())
            require(result["status"] == unit.expected_status, "matcher conditional control differs")
            for name in ("current_facts", "current_behavioral_facts", "eligible_requirements",
                         "behavioral_satisfied_requirements", "runtime_refutations", "removed_task_ids"):
                require(result[name] == [], "conditional lookup granted runtime planning facts")
            require({item["statement_id"] for item in result["residual_requirements"]} ==
                    {"mathematical-goal", "runtime-goal"}, "matcher lost a required residual")
            for name in ("kernel_checked", "proof_authority", "execution_authority", "completion_authority",
                         "admission_authority", "behavioral_satisfaction", "recorded_execution_attested"):
                require(result[name] is False, "matcher promoted conditional authority")
            matcher_results.append({"path": unit.path, "wall_seconds": time.perf_counter() - started,
                                    "result": result})
    return {"measurements": measurements, "entry_ids": expected_entries, "matcher_controls": matcher_results}


def replay(request):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
        CodebaseVerificationSelector, CodebaseVerificationQueryCursor,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
    audit = ProcessAudit()
    sys.addaudithook(audit.observe)
    deadline = Deadline(request["timeout_seconds"], request["operation_timeout_seconds"])
    started = time.perf_counter()
    index, catalog, connection = open_index(Path(request["directory"]))
    open_seconds = time.perf_counter() - started
    try:
        result = query_suite(catalog, index, Path(request["directory"]), CodebaseHead.from_dict(request["head"]),
                             request["identities"], audit, deadline, 1)
        require(result["entry_ids"] == request["entry_ids"], "fresh-process entry identities changed")
        with audit.scope("lookup", only_git=True):
            resumed, resumed_pages = traverse(catalog, Path(request["directory"]) / "source",
                CodebaseHead.from_dict(request["head"]), CodebaseVerificationSelector(), deadline,
                cursor=CodebaseVerificationQueryCursor.from_dict(request["resume_cursor"]))
        require(resumed == request["entry_ids"][3:], "serialized cursor did not resume exact inventory")
        require(source_pins() == request["source_pins"], "fresh-process producer generation differs")
        require(not own_leases(get_global_resource_scheduler()), "fresh-process leases survived")
        return {"completed": True, "open_seconds": open_seconds, "queries": result,
                "resumed_entry_ids": resumed, "resumed_pages": resumed_pages,
                "process_audit": {"counts": audit.counts, "events": audit.events},
                "owned_leases_drained": True, "source_pins": source_pins()}
    finally:
        deadline.close()
        connection.close()


def controls(catalog, index, connection, directory, head, identities, audit, deadline):
    from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalogError
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import CodebaseVerificationSelector as Selector
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
    repository = directory / "source"
    result = {}
    with audit.scope("controls", only_git=True):
        for label, selector in (
            ("cross_source_key_empty", Selector(path=identities[0]["path"], canonical_key_id=identities[1]["key_id"])),
            ("cross_source_dependency_empty", Selector(path=identities[0]["path"], dependency_kind="source",
                                                       dependency_value=identities[1]["source_cid"])),
            ("wrong_authored_domain_empty", Selector(path=identities[0]["path"], requested_domain_cid=identities[1]["domain_cid"])),
        ):
            rows, pages = traverse(catalog, repository, head, selector, deadline)
            require(rows == [], "inexact selector inferred an evidence match")
            result[label] = pages
        first = catalog.query_current(repository, expected_head=head, selector=Selector(), page_size=3,
                                      **deadline.options())
        require(not first.complete, "fixture failed to exercise continuation")
        try:
            catalog.query_current(repository, expected_head=head, selector=Selector(path=identities[0]["path"]),
                                  page_size=3, cursor=first.next_cursor, **deadline.options())
        except CodebaseVerificationCatalogError as error:
            result["changed_selector_rejected_old_cursor"] = str(error)
        else:
            raise AssertionError("cursor accepted another exact selector")
        # Existing native artifact, new projection shape: no new solver execution.
        catalog.publish(repository, expected_head=head, verification_cid=identities[0]["verification_cid"],
                        operation_id="same-head-without-domain", **deadline.options())
        try:
            catalog.query_current(repository, expected_head=head, selector=Selector(), page_size=3,
                                  cursor=first.next_cursor, **deadline.options())
        except CodebaseVerificationCatalogError as error:
            result["same_head_append_rejected_old_cursor"] = str(error)
        else:
            raise AssertionError("same-head append accepted stale inventory cursor")
        entries, pages = traverse(catalog, repository, head, Selector(), deadline)
        require(len(entries) == 9 and index.current(head.repository_id) == head, "append changed source head or lost entries")
        require(pages[0]["inventory_cid"] != first.inventory_cid and pages[0]["epoch"] > first.epoch,
                "same-head append did not advance sealed inventory")
        result["appended_entry_ids"] = entries
        result["inventory_before"] = first.to_dict()
        result["inventory_after"] = pages[0]
        corrupted = index.artifacts.path_for(identities[0]["projection_cid"])
        original = corrupted.read_bytes()
        try:
            corrupted.write_bytes(b"!" + original[1:])
            try:
                traverse(catalog, repository, head, Selector(path=identities[0]["path"]), deadline)
            except (CodebaseVerificationCatalogError, ValueError) as error:
                result["corrupt_projection_rejected"] = {"type": type(error).__name__, "message": str(error)}
            else:
                raise AssertionError("corrupt CAS projection was accepted")
        finally:
            corrupted.write_bytes(original)
        require(digest(corrupted.read_bytes()) == digest(original), "fault control did not restore exact artifact")
        path = repository / identities[0]["path"]
        raw = path.read_bytes()
        try:
            path.write_bytes(raw + b"# source changed\n")
            try:
                traverse(catalog, repository, head, Selector(), deadline)
            except StaleCodebaseError as error:
                result["dirty_source_rejected"] = str(error)
            else:
                raise AssertionError("dirty source remained current")
        finally:
            path.write_bytes(raw)
        successor = index.prepare_current(repository, repository_id=head.repository_id,
            operation_id="same-bytes-successor", expected_head=head, **deadline.options()).head
        require(successor.snapshot_cid == head.snapshot_cid and successor.generation > head.generation,
                "ABA control did not preserve bytes and advance generation")
        try:
            traverse(catalog, repository, head, Selector(), deadline)
        except StaleCodebaseError as error:
            result["old_generation_rejected"] = str(error)
        else:
            raise AssertionError("old generation remained eligible")
        rows, _ = traverse(catalog, repository, successor, Selector(), deadline)
        require(rows == [], "old conditional evidence leaked into successor head")
        result["successor_head"] = successor.to_dict()
        result["successor_has_no_inherited_evidence"] = True
    return result


def benchmark(directory: Path, report: dict, *, rounds: int, seconds: float, operation_seconds: float) -> None:
    import duckdb
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
    from ipfs_datasets_py.logic.software_contracts.codebase_verification import verify_current_codebase_unit
    from ipfs_datasets_py.logic.software_contracts.codebase_applicability import verify_current_codebase_applicability
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
    audit = ProcessAudit()
    sys.addaudithook(audit.observe)
    owner = get_global_resource_scheduler()
    require(owner.config.proof_safety_enabled, "default resource safety must be enabled")
    require(not own_leases(owner), "benchmark process already owns unrelated leases")
    report["source_pins_before"] = source_pins()
    report["scheduler_before"] = owner.snapshot()
    report["runtime"] = {"python": sys.version, "duckdb": duckdb.__version__, "platform": platform.platform(),
                         "machine": platform.machine(), "logical_cpu_count": os.cpu_count()}
    deadline = Deadline(seconds, operation_seconds)
    telemetry = Telemetry(owner)
    telemetry.thread.start()
    connection = None
    try:
        progress(directory, report, "fixture")
        repository = directory / "source"
        repository.mkdir()
        for unit in fixture_units():
            (repository / unit.path).write_bytes(unit.source)
        with audit.scope("fixture"):
            for args in (("init", "-q"), ("config", "user.name", "Evidence Query Fixture"),
                         ("config", "user.email", "fixture@example.invalid"), ("add", "."),
                         ("commit", "-qm", "bounded native fixture")):
                subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, timeout=10)
        index, catalog, connection = open_index(directory)
        started = time.perf_counter()
        with audit.scope("prepare"):
            head = index.prepare_current(repository, repository_id=VIEW, operation_id="initial", expected_head=None,
                                         **deadline.options()).head
        report.update(head=head.to_dict(), prepare_seconds=time.perf_counter() - started, producers=[], identities=[])
        progress(directory, report, "prepared")
        for number, unit in enumerate(fixture_units()):
            contract, domain = unit.native()
            progress(directory, report, "verification:" + unit.path)
            started = time.perf_counter()
            with audit.scope("verification"):
                verification = verify_current_codebase_unit(index, repository, expected_head=head, path=unit.path,
                                                            contracts=[contract], **deadline.options())
            verification_seconds = time.perf_counter() - started
            report["last_verification"] = {"path": unit.path, "artifact_cid": verification.artifact_cid,
                                           "wall_seconds": verification_seconds}
            progress(directory, report, "applicability:" + unit.path)
            started = time.perf_counter()
            with audit.scope("applicability"):
                applicability = verify_current_codebase_applicability(index, repository, expected_head=head,
                    verification_cid=verification.artifact_cid, domains=[domain], **deadline.options())
            applicability_seconds = time.perf_counter() - started
            report["last_applicability"] = {"path": unit.path, "artifact_cid": applicability.artifact_cid,
                                            "wall_seconds": applicability_seconds}
            progress(directory, report, "publication:" + unit.path)
            started = time.perf_counter()
            with audit.scope("publish", only_git=True):
                projection = catalog.publish(repository, expected_head=head, verification_cid=verification.artifact_cid,
                    applicability_cid=applicability.artifact_cid, operation_id=f"publish:{number}", **deadline.options())
            value, app = projection.to_dict(), applicability.to_dict()
            selected = value["contracts"][0]
            require(len(selected["canonical_keys"]) == 1 and len(selected["applicability_keys"]) == 4,
                    "native fixture obligation inventory differs")
            require(len(verification.to_dict()["process_observations"]) == 2 and len(app["process_observations"]) == 8,
                    "native query observation count differs")
            require(applicability.conditional_proved is (number < 6), "proved applicability control differs")
            require(applicability.conditional_refuted is (number == 6), "refuted applicability control differs")
            require(app["contract_results"][0]["status"] == ("empty_domain" if number == 7 else "established"),
                    "domain gate differs")
            report["producers"].append({"path": unit.path, "verification_seconds": verification_seconds,
                "applicability_seconds": applicability_seconds, "publication_seconds": time.perf_counter() - started,
                "verification_cid": verification.artifact_cid, "applicability_cid": applicability.artifact_cid,
                "projection_cid": projection.projection_cid, "canonical_keys": selected["canonical_keys"] + selected["applicability_keys"],
                "query_observations": 10, "environment": verification.to_dict()["environment"],
                "applicability_status": app["contract_results"][0], "expected_matcher_status": unit.expected_status})
            report["identities"].append({"path": unit.path, "contract_id": contract.contract_id,
                "contract_cid": cid_for_structured(contract.to_dict()), "domain_id": domain.domain_id,
                "domain_cid": cid_for_structured(domain.to_dict()), "verification_cid": verification.artifact_cid,
                "source_cid": value["source_binding"]["entry"]["source_cid"], "projection_cid": projection.projection_cid,
                "key_id": selected["canonical_keys"][0]["key_id"]})
            require(not own_leases(owner), "producer leaked an owned lease")
            progress(directory, report, "published:" + unit.path)
        progress(directory, report, "queries")
        report["queries"] = query_suite(catalog, index, directory, head, report["identities"], audit, deadline, rounds)
        progress(directory, report, "queries_completed")
        connection.close()
        connection = None
        request = {"directory": str(directory), "head": head.to_dict(), "identities": report["identities"],
                   "entry_ids": report["queries"]["entry_ids"], "source_pins": report["source_pins_before"],
                   "resume_cursor": report["queries"]["measurements"][0]["pages"][0]["next_cursor"],
                   "timeout_seconds": deadline.options()["timeout_seconds"], "operation_timeout_seconds": operation_seconds}
        request_path = directory / "restart-request.json"
        request_path.write_text(json.dumps(request))
        progress(directory, report, "fresh_process_replay")
        started = time.perf_counter()
        with audit.scope("restart_launcher"):
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path)],
                capture_output=True, text=True, timeout=min(deadline.end - time.monotonic(), operation_seconds + 10))
        (directory / "restart.stdout").write_text(child.stdout)
        (directory / "restart.stderr").write_text(child.stderr)
        require(child.returncode == 0, "fresh-process replay failed: " + child.stderr[-4000:])
        report["restart"] = json.loads(child.stdout.splitlines()[-1])
        report["restart"]["wall_seconds_including_startup"] = time.perf_counter() - started
        progress(directory, report, "fresh_process_completed")
        index, catalog, connection = open_index(directory)
        progress(directory, report, "controls")
        started = time.perf_counter()
        report["controls"] = controls(catalog, index, connection, directory, head, report["identities"], audit, deadline)
        report["controls_seconds"] = time.perf_counter() - started
        progress(directory, report, "controls_completed")
        report["table_counts"] = {schema + "." + table: connection.execute(
            'SELECT count(*) FROM "' + schema.replace('"', '""') + '"."' + table.replace('"', '""') + '"').fetchone()[0]
            for schema, table in connection.execute("SELECT schema_name,table_name FROM duckdb_tables() WHERE NOT internal ORDER BY schema_name,table_name").fetchall()}
        require(time.monotonic() < deadline.end, "benchmark exceeded declared overall deadline")
        report["completed"] = True
    finally:
        deadline.close()
        if connection is not None:
            connection.close()
        report["source_pins_after"] = source_pins()
        report["process_audit"] = {"counts": audit.counts, "events": audit.events}
        report["scheduler_after"] = owner.snapshot()
        report["owned_leases_at_return"] = own_leases(owner)
        report["telemetry"] = telemetry.finish()
        report["checks"] = {
            "completed": report.get("completed") is True,
            "selected_sources_unchanged": report["source_pins_after"] == report["source_pins_before"],
            "owned_leases_drained": report["owned_leases_at_return"] == [],
            "native_query_observations": sum(item["query_observations"] for item in report.get("producers", [])) == 80,
            "actual_native_query_launches": sum(value for key, value in audit.counts.items()
                if key.endswith(":solver_query")) == 80,
            "actual_native_version_launches": sum(value for key, value in audit.counts.items()
                if key.endswith(":version")) == 80,
            "lookup_no_solver_or_version_processes": all(event["kind"] == "git" for event in audit.events
                if event["stage"] in {"lookup", "publish", "controls"}),
            "fresh_process_replay": report.get("restart", {}).get("completed") is True,
            "sampler_stopped": report["telemetry"]["sampler_stopped"],
            "telemetry_without_errors": report["telemetry"]["errors"] == [],
        }
        progress(directory, report, "completed" if report.get("completed") else "failed")
    require(all(report["checks"].values()), "benchmark correctness/source/cleanup checks failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--overall-timeout", type=float, default=600)
    parser.add_argument("--operation-timeout", type=float, default=120)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ACCELERATE))
    if args.replay:
        raw = args.replay.read_bytes()
        require(len(raw) <= 128 * 1024, "replay request exceeds finite input bound")
        print(json.dumps(replay(json.loads(raw))))
        return 0
    if args.output is None:
        parser.error("--output is required")
    require(0 < args.operation_timeout <= args.overall_timeout <= 900, "timeouts must be finite within900seconds")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    require(not (directory / "result.json").exists() and not (directory / "source").exists(), "output already contains an attempt")
    report = {"schema": SCHEMA, "started_at_utc": datetime.now(timezone.utc).isoformat(), "completed": False,
        "configuration": {"units": 8, "query_rounds": args.rounds, "page_size": 3, "duckdb": DB_CONFIG,
            "overall_timeout_seconds": args.overall_timeout, "operation_timeout_seconds": args.operation_timeout,
            "scheduler": "shared_default", "sequential_producers": True},
        "scope": {"conditional_model_evidence_only": True, "kernel_checked": False,
            "runtime_behavior_verified": False, "scaling_qualification": False, "network_requested": False,
            "producer_hard_rss_output_limits": False, "admission_is_hard_memory_limit": False,
            "deadline_includes_admission": True, "lookup_replays_historical_claims_without_attesting_execution": True},
        "errors": []}
    started = time.perf_counter()
    try:
        benchmark(directory, report, rounds=args.rounds, seconds=args.overall_timeout,
                  operation_seconds=args.operation_timeout)
    except BaseException as error:
        report["completed"] = False
        report["errors"].append({"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
    finally:
        report["wall_seconds"] = time.perf_counter() - started
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (directory / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": str(directory / "result.json"), "completed": report["completed"],
                      "wall_seconds": report["wall_seconds"], "checks": report.get("checks", {})}))
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
