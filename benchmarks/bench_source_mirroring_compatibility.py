"""Fresh conditional proof records after an explicit producer source evolution.

Two finite native Z3/CVC5 fixtures establish a new source generation. Retained
@1/@2 sidecars must reject it without relabelling their hashes or mutating their
catalog/CAS. Fresh lookups replay recorded claims, never attest execution or
grant runtime, planning, training, admission, or completion authority.
"""
from __future__ import annotations

import argparse
from collections import Counter
from functools import wraps
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

import bench_codebase_evidence_queries as base
import bench_codebase_smt_execution as bounded
import bench_smt_operation_control as guard
import bench_tla_outcome_integrity as previous
from bench_generic_prover_admission import LaunchAudit
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write

HISTORICAL = (
    ROOT / "workspace/codebase-evidence-query-qualification-20261002/native",
    ROOT / "workspace/codebase-smt-execution-qualification-20261002/native-bound-input",
)
UNITS = (base.fixture_units()[0], base.fixture_units()[6])
CHANGED_MODULES = {
    "ipfs_datasets_py.logic.software_verification.pipeline",
    "ipfs_datasets_py.logic.software_verification.source_adapters",
    "ipfs_datasets_py.logic.software_contracts.codebase_integer_profile",
}
CONSUMER_MODULES = (
    "ipfs_datasets_py.logic.intent_ir.schema",
    "ipfs_accelerate_py",
    "ipfs_accelerate_py.agent_supervisor",
    "ipfs_accelerate_py.agent_supervisor.planning",
    "ipfs_accelerate_py.agent_supervisor.planning.conditional_codebase_evidence",
    "ipfs_accelerate_py.agent_supervisor.planning.structural_codebase_context",
)


def consumer_sources():
    result = {}
    for name in CONSUMER_MODULES:
        path = Path(importlib.import_module(name).__file__).resolve()
        if name.startswith("ipfs_accelerate_py"):
            require(base.ACCELERATE in path.parents, "conditional consumer resolved outside selected sibling checkout")
        result[name] = {"path": str(path), "sha256": sha(path)}
    return result


def duckdb_dependency():
    """Identify selected installed DuckDB components, not the Python environment."""
    import duckdb
    import _duckdb

    def bounded_hash(path, maximum):
        require(path.is_file() and 0 < path.stat().st_size <= maximum,
                "installed DuckDB component exceeds the reviewed finite bound")
        digest, count = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(MIB), b""):
                count += len(block)
                require(count <= maximum, "installed DuckDB component grew beyond the finite bound")
                digest.update(block)
        return digest.hexdigest()

    package_init = Path(duckdb.__file__).resolve()
    extension = Path(_duckdb.__file__).resolve()
    root = package_init.parent.parent
    require(package_init.name == "__init__.py" and package_init.parent.name == "duckdb"
            and extension.parent == root and extension.name.startswith("_duckdb.")
            and extension.suffix == ".so", "DuckDB package/extension installation layout differs")
    require(type(duckdb.__version__) is str and 0 < len(duckdb.__version__) <= 64
            and duckdb.__version__ == _duckdb.__version__, "DuckDB Python/native versions differ")
    package_files = sorted(package_init.parent.rglob("*.py"))
    require(0 < len(package_files) <= 128
            and sum(path.stat().st_size for path in package_files) <= 8 * MIB,
            "DuckDB Python package inventory exceeds the finite bound")
    require(all(path.resolve().is_relative_to(package_init.parent) for path in package_files),
            "DuckDB Python package escapes its selected installation")
    return {"version": duckdb.__version__, "installation_root": str(root),
        "package_init": {"path": str(package_init), "sha256": bounded_hash(package_init, MIB)},
        "native_extension": {"path": str(extension), "sha256": bounded_hash(extension, 128 * MIB)},
        "package_python_files": {str(path.resolve()): bounded_hash(path, MIB) for path in package_files},
        "scope": "selected installed DuckDB Python sources and native extension; no full environment attestation"}


def inventories():
    from ipfs_datasets_py.logic.software_contracts import codebase_verification as v, codebase_applicability as a
    return {"verification": v._module_pins(), "applicability": a._pins()}


def pins():
    # Complete *actual* producer inventories supplement the older runtime pin
    # set. In particular integer_profile was absent from earlier manifests.
    from ipfs_datasets_py.logic.software_contracts import codebase_verification as v, codebase_applicability as a
    paths = [Path(importlib.import_module(name).__file__).resolve()
             for name in (*v._MODULES, *a._EXTRA_MODULES)]
    paths += [Path(row["path"]) for row in consumer_sources().values()]
    paths += [Path(__file__), Path(base.__file__), Path(bounded.__file__)]
    return {**previous.pins(), **bounded.source_pins(),
            **{str(path.resolve()): sha(path) for path in paths}}


def original_inventory(directory):
    database = directory / "catalog.duckdb"
    require(database.is_file() and database.stat().st_size <= 256 * MIB
            and not database.with_suffix(".duckdb.wal").exists(), "historical database is unbounded or live")
    return {"database_sha256": sha(database), "result_sha256": sha(directory / "result.json"),
            "cas": saved.artifact_hashes(directory / "artifacts"),
            "source": saved.artifact_hashes(directory / "source")}


def raw_sidecar(directory, cid):
    return saved.read_json(directory / "artifacts/structured" / cid[:4] / cid, 16 * MIB)


def open_historical(directory, scratch):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    scratch.mkdir()
    database = scratch / "catalog.duckdb"
    shutil.copy2(directory / "catalog.duckdb", database)
    require(sha(database) == sha(directory / "catalog.duckdb"), "closed database copy differs")
    cx = duckdb.connect(str(database), config=base.DB_CONFIG)
    store = DuckDBASTStore(connection=cx)
    # Preserve the stored absolute artifact-root binding. Only the copied DB
    # receives ordinary constructor writes; no catalog-root rebinding occurs.
    artifacts = ImmutableCAS(directory / "artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    return index, CodebaseVerificationCatalog(index), cx, store


class Audit(LaunchAudit):
    """Delegate real admission/lifecycles; observe nested closed-producer leases."""

    def __init__(self, owner):
        super().__init__(owner)
        self.processes = bounded.ProcessAudit()
        self.replay_launches = LaunchAudit(owner)
        self.replay_launches.local = self.local
        self.replay_results = []

    def install_observers(self):
        from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
        acquire = self.owner.acquire

        def observed_acquire(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            prior = getattr(self.local, "lease", None)
            self.local.lease = lease
            release = lease.release

            def observed_release():
                try:
                    return release()
                finally:
                    self.local.lease = prior
            lease.release = observed_release
            return lease

        self.owner.acquire = observed_acquire
        run = BoundedToolRunner.run

        # The source-generation guard unwraps transparent observers to their
        # unchanged implementation. No producer, classification or receipt is
        # substituted; the original runner owns all execution and cleanup.
        @wraps(run)
        def observed_run(runner, request, **kwargs):
            value = run(runner, request, **kwargs)
            stdin = request.stdin or b""
            if isinstance(stdin, str):
                stdin = stdin.encode()
            row = {"case": getattr(self.local, "case", "setup"), "result": value.to_dict(),
                "request": {"argv": list(request.argv), "input_sha256": hashlib.sha256(stdin).hexdigest(),
                    "input_file_count": len(request.input_files), "output_path_count": len(request.output_paths),
                    "limits": {name: getattr(request.limits, name) for name in (
                        "timeout_seconds", "cpu_seconds", "memory_bytes", "resident_memory_bytes",
                        "max_output_bytes", "max_input_bytes", "max_workspace_bytes", "max_file_bytes",
                        "termination_grace_seconds")}}}
            target = self.results if Path(request.argv[0]).name in {"z3", "cvc5"} else self.replay_results
            require(len(target) < 64, "bounded lifecycle audit exceeded")
            target.append(row)
            return value

        BoundedToolRunner.run = observed_run

    def observe(self, event, arguments):
        if event != "subprocess.Popen":
            return
        self.processes.observe(event, arguments)
        row = self.processes.events[-1]
        if row["kind"] in {"version", "solver_query"}:
            require(self.processes.stage in {"verification", "applicability"}, "solver started outside fresh production")
            super().observe(event, arguments)
        elif row["kind"] != "git":
            require(self.processes.stage == "fresh_process" and len(self.replay_launches.events) == 0
                    and Path(row["logical_argv"][0]).resolve() == Path(sys.executable).resolve(),
                    "unexpected helper process in qualification")
            self.replay_launches.observe(event, arguments)


def reject_historical(directory, scratch, audit, deadline, current):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import CodebaseVerificationSelector
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
    from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
    from ipfs_datasets_py.logic.software_contracts.codebase_verification import load_codebase_verification, CodebaseVerificationError
    from ipfs_datasets_py.logic.software_contracts.codebase_applicability import load_codebase_applicability, CodebaseApplicabilityError
    metadata = saved.read_json(directory / "result.json", 32 * MIB)
    require(len(metadata["producers"]) == 8, "historical fixture inventory differs")
    rows = []
    with audit.processes.scope("historical", only_git=True):
        index, catalog, cx, store = open_historical(directory, scratch)
        try:
            with acquire_codebase_resources(memory_mb=512, timeout_seconds=30) as parent:
                with store._lock, store._transaction():
                    for producer in metadata["producers"]:
                        deadline.options()
                        item = {"path": producer["path"], "rejections": [], "module_changes": {}}
                        for kind, loader, error_type in (("verification", load_codebase_verification, CodebaseVerificationError),
                                ("applicability", load_codebase_applicability, CodebaseApplicabilityError)):
                            cid = producer[kind + "_cid"]
                            raw = raw_sidecar(directory, cid)
                            recorded = {pin["module"]: pin["sha256"] for pin in raw["environment"]["module_pins"]}
                            now = {pin["module"]: pin["sha256"] for pin in current[kind]}
                            changed = {name: {"historical": value, "current": now.get(name)}
                                       for name, value in recorded.items() if now.get(name) != value}
                            # @1 additionally has the intentionally evolved
                            # containment owners; all three semantic changes
                            # must be visible in both generations.
                            require(CHANGED_MODULES <= set(changed), "historical semantic source drift missing")
                            if raw["schema"].endswith("@2"):
                                require(set(changed) == CHANGED_MODULES, "unreviewed @2 producer dependency drift")
                            item["module_changes"][kind] = changed
                            expected = ("legacy semantic dependency changed; explicit migration required"
                                if raw["schema"].endswith("@1") else
                                "historical implementation generation differs; explicit migration required")
                            try:
                                loader(index, cid)
                            except error_type as error:
                                require(str(error) == expected, "sidecar failed for a reason other than exact source generation")
                                item["rejections"].append({"kind": kind, "cid": cid, "schema": raw["schema"],
                                    "error_type": type(error).__name__, "message": str(error)})
                            else:
                                raise AssertionError("historical sidecar inherited new producer authority")
                        try:
                            catalog._read(producer["projection_cid"])
                        except CodebaseVerificationError as error:
                            require("explicit migration required" in str(error), "projection rejection lost generation reason")
                            item["projection_rejection"] = {"cid": producer["projection_cid"],
                                "error_type": type(error).__name__, "message": str(error)}
                        else:
                            raise AssertionError("historical projection accepted current producer generation")
                        rows.append(item)
                controls = metadata.get("query_controls", metadata.get("controls"))
                current_head = CodebaseHead.from_dict(controls["successor_head"])
                require(index.current(current_head.repository_id) == current_head, "original stored head binding differs")
                try:
                    catalog.query_current(directory / "source", expected_head=CodebaseHead.from_dict(metadata["head"]),
                        selector=CodebaseVerificationSelector(), parent_lease=parent, **deadline.options())
                except StaleCodebaseError:
                    pass
                else:
                    raise AssertionError("retained historical head became current")
                page = catalog.query_current(directory / "source", expected_head=current_head,
                    selector=CodebaseVerificationSelector(), parent_lease=parent, **deadline.options())
                require(page.complete and not page.entries, "retained evidence leaked into successor head")
        finally:
            cx.close()
    return {"directory": str(directory), "cas_root_preserved": str(directory / "artifacts"),
            "pairs": rows, "sidecar_rejections": 16, "projection_rejections": 8,
            "old_head_rejected": True, "successor_empty": True}


def query_fresh(index, catalog, directory, head, identities, audit, deadline):
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import CodebaseVerificationSelector as Selector
    from ipfs_accelerate_py.agent_supervisor.planning import conditional_codebase_evidence as matcher
    rows = []
    with audit.scope("lookup", only_git=True):
        entries, pages = base.traverse(catalog, directory / "source", head, Selector(), deadline, page_size=1)
        require(len(entries) == 2 and len(pages) == 2, "fresh conditional inventory differs")
        require((entries, pages) == base.traverse(catalog, directory / "source", head, Selector(), deadline, page_size=1),
                "stable query page bytes changed")
        for unit, identity in zip(UNITS, identities):
            contract, domain = unit.native()
            selected, selected_pages = base.traverse(catalog, directory / "source", head,
                Selector(path=unit.path, verification_cid=identity["verification_cid"],
                         canonical_key_id=identity["key_id"]), deadline)
            require(len(selected) == 1 and selected[0] in entries, "fresh exact key did not select one row")
            stale_entries, stale_pages = base.traverse(catalog, directory / "source", head,
                Selector(path=unit.path, canonical_key_id=identity["historical_key_id"]), deadline)
            require(stale_entries == [], "fresh catalog aliased a historical canonical key")
            text, document = base.authored_intent(unit, contract, domain)
            result = matcher.match_conditional_codebase_intent(catalog=catalog, index=index,
                repository=directory / "source", repository_id=head.repository_id, expected_head=head,
                intent_document=document, source_text=text, path=unit.path, contract=contract, domain=domain,
                statement_id="mathematical-goal", verification_cid=identity["verification_cid"],
                expected_key_id=identity["key_id"], **deadline.options())
            require(result["status"] == unit.expected_status, "fresh conditional classification differs")
            for name in ("current_facts", "current_behavioral_facts", "eligible_requirements",
                         "behavioral_satisfied_requirements", "runtime_refutations", "removed_task_ids"):
                require(result[name] == [], "conditional evidence granted planning authority")
            require({row["statement_id"] for row in result["residual_requirements"]} ==
                    {"mathematical-goal", "runtime-goal"}, "required planning residual disappeared")
            for name in ("kernel_checked", "proof_authority", "execution_authority", "completion_authority",
                         "admission_authority", "behavioral_satisfaction", "recorded_execution_attested"):
                require(result[name] is False, "conditional evidence gained authority")
            rows.append({"path": unit.path, "pages": selected_pages, "historical_key_pages": stale_pages,
                         "historical_key_empty": True, "matcher": result})
    return {"entry_ids": entries, "pages": pages, "selected": rows}


def check_native_phases(audit, observations, label):
    phases = [phase for observation in observations for phase in observation["execution"]["phases"]]
    actual = [row for row in audit.results if row["case"] == label]
    launches = [row for row in audit.events if row["case"] == label]
    require(len(phases) == len(actual) == len(launches) == 30, "fixture did not execute 30 admitted native phases")
    for phase, row, launch in zip(phases, actual, launches):
        request, result = row["request"], row["result"]
        require(phase["argv"] == request["argv"] and phase["input_sha256"] == request["input_sha256"],
                "recorded native argv/input differs from executed request")
        require(result["pid"] is not None and result["returncode"] == 0 and result["workspace_cleaned"]
                and not result["error"] and not any(result[key] for key in (
                    "timed_out", "cancelled", "unavailable", "resource_exhausted", "output_truncated",
                    "workspace_limit_exceeded", "process_tree_terminated")), "native SMT phase failed or leaked")
        require(not Path("/proc", str(result["pid"])).exists(), "native PID survived cleanup")
        require(all(phase[key] == result[key] for key in ("stdout", "stderr", "returncode", "workspace_cleaned",
                "error", "cancelled", "timed_out", "unavailable", "resource_exhausted", "output_truncated",
                "process_tree_terminated")), "retained phase differs from actual lifecycle")
        limits = request["limits"]
        require(0 < limits["timeout_seconds"] <= 5 and 0 < limits["cpu_seconds"] <= 5
                and limits["memory_bytes"] == limits["resident_memory_bytes"] == 128 * MIB
                and limits["max_output_bytes"] == (4096 if phase["kind"] == "version" else 262144)
                and limits["max_input_bytes"] == 262144
                and limits["max_workspace_bytes"] == limits["max_file_bytes"] == 16 * MIB
                and limits["termination_grace_seconds"] == .25,
                "native SMT phase lost finite reviewed resource profile")
        lease = next(item for item in launch["owned_leases"] if item["lease_id"] == launch["launch_lease_id"])
        require(lease["parent_lease_id"] and lease["cpu_slots"] == lease["child_process_slots"] == 1
                and lease["memory_mb"] == 128, "native phase lacks its actual bounded child lease")
        logical = launch["argv"][launch["argv"].index("--") + 1:]
        require(logical == request["argv"], "Popen command differs from native request")
    require(len({row["launch_lease_id"] for row in launches}) == 30, "native phases reused a child lease")
    return dict(Counter(phase["kind"] for phase in phases))


def produce(directory, audit, deadline, current):
    from ipfs_datasets_py.logic.software_contracts.codebase_verification import verify_current_codebase_unit
    from ipfs_datasets_py.logic.software_contracts.codebase_applicability import verify_current_codebase_applicability
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
    directory.mkdir()
    # Preserve identical source bytes, commit and snapshot identity in a fresh
    # independent repository/catalog; copy includes only this finite fixture.
    shutil.copytree(HISTORICAL[1] / "source", directory / "source")
    index, catalog, cx = base.open_index(directory)
    rows, identities = [], []
    try:
        with audit.processes.scope("prepare", only_git=True):
            head = index.prepare_current(directory / "source", repository_id=base.VIEW,
                operation_id="initial", expected_head=None, **deadline.options()).head
        old_metadata = saved.read_json(HISTORICAL[1] / "result.json", 32 * MIB)
        require(head.snapshot_cid == old_metadata["head"]["snapshot_cid"], "fresh copied repository changed source snapshot")
        for unit in UNITS:
            started = time.monotonic()
            audit.local.case = unit.path
            contract, domain = unit.native()
            with audit.processes.scope("verification"):
                verification = verify_current_codebase_unit(index, directory / "source", expected_head=head,
                    path=unit.path, contracts=[contract], **deadline.options())
            with audit.processes.scope("applicability"):
                applicability = verify_current_codebase_applicability(index, directory / "source", expected_head=head,
                    verification_cid=verification.artifact_cid, domains=[domain], **deadline.options())
            with audit.processes.scope("publish", only_git=True):
                projection = catalog.publish(directory / "source", expected_head=head,
                    verification_cid=verification.artifact_cid, applicability_cid=applicability.artifact_cid,
                    operation_id="publish:" + unit.path, **deadline.options())
            base.assert_authority(projection)
            v, a, p = verification.to_dict(), applicability.to_dict(), projection.to_dict()
            require(v["environment"]["module_pins"] == current["verification"]
                    and a["environment"]["module_pins"] == current["applicability"], "fresh producer inventory differs")
            require(v["pipeline"]["include_supervisor_evidence"] is False, "fresh producer invoked optional supervisor evidence")
            require(applicability.conditional_proved is (unit.path == "unit_00.py")
                    and applicability.conditional_refuted is (unit.path == "unit_06.py"), "fresh domain verdict differs")
            for value in (v, a):
                require(value["authority"]["authoritative_cache_eligible"] is False
                        and not any(flag for name, flag in value["authority"].items()
                                    if name not in {"conditional_model_evidence", "typed_model_evidence_only"}),
                        "sidecar authority exceeded conditional scope")
            old = next(row for row in old_metadata["producers"] if row["path"] == unit.path)
            comparisons = []
            for kind, value in (("verification", v), ("applicability", a)):
                retained = raw_sidecar(HISTORICAL[1], old[kind + "_cid"])
                scripts = [item["compilation"]["smtlib"] for item in value["solver_artifacts" if kind == "verification" else "checks"]]
                old_scripts = [item["compilation"]["smtlib"] for item in retained["solver_artifacts" if kind == "verification" else "checks"]]
                require(scripts == old_scripts, "fresh semantic SMT changed from retained fixture")
                require(value["source_binding"]["content_sha256"] == retained["source_binding"]["content_sha256"],
                        "fresh source bytes changed")
                require(len(value["canonical_keys"]) == len(retained["canonical_keys"])
                        and all(now != then and now["environment"] != then["environment"]
                            for now, then in zip(value["canonical_keys"], retained["canonical_keys"])),
                        "fresh source generation reused historical cache environment/key")
                comparisons.append({"kind": kind, "old_cid": old[kind + "_cid"],
                    "old_keys": retained["canonical_keys"], "fresh_keys": value["canonical_keys"],
                    "same_semantic_smt": True, "same_source_bytes": True,
                    "script_sha256": [hashlib.sha256(script.encode()).hexdigest() for script in scripts]})
            observations = v["process_observations"] + a["process_observations"]
            require(len(observations) == 10, "fixture observation count differs")
            phase_counts = check_native_phases(audit, observations, unit.path)
            selected = p["contracts"][0]
            identity = {"path": unit.path, "verification_cid": verification.artifact_cid,
                "applicability_cid": applicability.artifact_cid, "projection_cid": projection.projection_cid,
                "key_id": selected["canonical_keys"][0]["key_id"], "contract_id": contract.contract_id,
                "historical_key_id": old["canonical_keys"][0]["key_id"],
                "contract_cid": cid_for_structured(contract.to_dict()), "domain_id": domain.domain_id,
                "domain_cid": cid_for_structured(domain.to_dict()), "source_cid": p["source_binding"]["entry"]["source_cid"]}
            identities.append(identity)
            rows.append({**identity, "elapsed_seconds": time.monotonic() - started, "phase_counts": phase_counts,
                "phase_count": 30, "comparisons": comparisons, "observations": observations,
                "verification": v, "applicability": a, "projection": p})
        query = query_fresh(index, catalog, directory, head, identities, audit.processes, deadline)
        return {"head": head.to_dict(), "producers": rows, "identities": identities, "fresh_queries": query}
    finally:
        cx.close()


def replay(request_path):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    request = saved.read_json(request_path, 256 * 1024)
    dependency = duckdb_dependency()
    require(dependency == request["duckdb_dependency"], "cold replay loaded another DuckDB dependency generation")
    owner, envelope = guard.install_saved_owner(Path(request["config_path"]))
    audit = bounded.ProcessAudit()
    audit.only_git = True
    sys.addaudithook(audit.observe)
    before = pins()
    deadline = base.Deadline(80, 30)
    directory = Path(request["directory"])
    index, catalog, cx = base.open_index(directory)
    try:
        result = query_fresh(index, catalog, directory, CodebaseHead.from_dict(request["head"]),
                             request["identities"], audit, deadline)
        require(pins() == before, "fresh replay source pins drifted")
        require(duckdb_dependency() == dependency, "fresh replay DuckDB dependency drifted")
        require(all(event["kind"] == "git" for event in audit.events), "fresh replay launched a solver")
        pool = saved.state_summary(owner.state_path)
        require(not pool["owned_active_leases"] and not pool["owned_waiting_requests"], "fresh replay leaked resources")
        write(Path(request["result_path"]), {"status": "passed", "queries": result,
            "source_pins": before, "producer_inventories": inventories(), "processes": audit.events,
            "consumer_sources": consumer_sources(), "shared_after": pool, "source_generation": "current",
            "duckdb_dependency": dependency, "historical_execution_attested": False})
    finally:
        cx.close()
        deadline.close()


def bounded_replay(directory, report, owner, audit, deadline):
    from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
    request_path = directory / "replay-request.json"
    result_path = directory / "replay-result.json"
    write(request_path, {"directory": str(directory / "fresh"), "head": report["head"],
        "identities": report["identities"], "config_path": str(directory / "saved-scheduler-config.json"),
        "duckdb_dependency": report["duckdb_dependency_before"], "result_path": str(result_path)})
    audit.local.case = "fresh_process"
    # Python owns one process slot; its separately admitted snapshot queries
    # own their Git slot. Reservations fit the unchanged four-slot pool.
    with audit.processes.scope("fresh_process"):
        with owner.acquire("validation", cpu_slots=1, memory_mb=1024, child_process_slots=1,
                           timeout=30, cancel_event=deadline.cancelled) as parent:
            result = BoundedToolRunner().run(ToolRunRequest(
                argv=(sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path)),
                limits=ToolRunLimits(timeout_seconds=min(90, deadline.options()["timeout_seconds"]),
                    cpu_seconds=60, memory_bytes=4 * 1024**3, resident_memory_bytes=1024 * MIB,
                    max_output_bytes=MIB, max_input_bytes=1024, max_workspace_bytes=16 * MIB,
                    max_file_bytes=16 * MIB),
                # Plain PYTHONPATH does not execute site-package .pth files.
                # Private HOME and the selected consumer precedence remain;
                # only this recorded installed dependency root is appended.
                environment={"PYTHONPATH": os.pathsep.join((str(base.ACCELERATE), str(ROOT),
                        report["duckdb_dependency_before"]["installation_root"])),
                    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0", "IPFS_TEST_PROOF_REUSE_MODE": "off",
                    "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                    "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}),
                cancellation=parent.combined_cancellation_signal(deadline.cancelled))
    require(len(audit.replay_launches.events) == len(audit.replay_results) == 1,
            "fresh replay did not execute exactly one observed helper lifecycle")
    expected = [sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path)]
    launch = audit.replay_launches.events[0]
    logical = launch["argv"][launch["argv"].index("--") + 1:]
    require(Path(logical[0]).resolve() == Path(expected[0]).resolve() and logical[1:] == expected[1:]
            and audit.replay_results[0]["request"]["argv"] == expected,
            "fresh replay actual helper argv differs from the bounded reviewed request")
    lease = next(row for row in launch["owned_leases"] if row["lease_id"] == launch["launch_lease_id"])
    require(not lease.get("parent_lease_id") and lease["cpu_slots"] == lease["child_process_slots"] == 1
            and lease["memory_mb"] == 1024, "fresh replay lost its actual bounded helper reservation")
    require(result.returncode == 0 and result.workspace_cleaned and not result.error
            and not any(getattr(result, name) for name in ("timed_out", "cancelled", "unavailable", "resource_exhausted",
                "output_truncated", "workspace_limit_exceeded", "process_tree_terminated")),
            "bounded fresh replay failed: " + result.stderr)
    require(not Path("/proc", str(result.pid)).exists(), "fresh replay PID survived cleanup")
    value = saved.read_json(result_path, 16 * MIB)
    require(value["queries"] == report["fresh_queries"] and value["source_pins"] == report["source_pins_before"]
            and value["producer_inventories"] == report["producer_inventories"]
            and value["consumer_sources"] == report["consumer_sources"]
            and value["duckdb_dependency"] == report["duckdb_dependency_before"],
            "fresh process reconstructed different evidence or dependency identity")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(base.ACCELERATE))
    if args.replay is not None:
        replay(args.replay.resolve())
        return 0
    if args.output is None:
        parser.error("--output is required")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    result = {"schema": "source-mirroring-compatibility-benchmark@1", "status": "running", "checks": {},
        "source_pins_before": pins(), "producer_inventories": inventories(),
        "consumer_sources": consumer_sources(),
        "duckdb_dependency_before": duckdb_dependency(),
        "scope": {"conditional_evidence_only": True, "historical_execution_attested": False,
            "metadata_mirroring": "native-only producers omit optional supervisor evidence",
            "training_performed": False, "scaling_qualification": False, "hash_aliases": False}}
    write(directory / "command.json", {"argv": sys.argv, "cwd": str(Path.cwd())})
    deadline, owner, audit, envelope = None, None, None, None
    started = time.monotonic()
    try:
        result["original_before"] = {str(path): original_inventory(path) for path in HISTORICAL}
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = guard.install_saved_owner(directory / "saved-scheduler-config.json")
        result["shared_before"] = saved.state_summary(owner.state_path)
        result["shared_pool_compatibility"] = owner._benchmark_pool_compatibility
        audit = Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        require(inventories() == result["producer_inventories"], "transparent observer changed producer identity")
        deadline = base.Deadline(600, 120)
        result["historical_rejections"] = [reject_historical(path, directory / f"historical-copy-{number}",
            audit, deadline, result["producer_inventories"]) for number, path in enumerate(HISTORICAL, 1)]
        # Resolve and hash exactly the installed launchers/binaries selected by
        # the closed producer, without probing or installing them.
        from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import _native_executable
        tool_paths = []
        for name in ("z3", "cvc5"):
            launcher = shutil.which(name)
            require(launcher is not None, "installed solver is missing: " + name)
            executable, _ = _native_executable(launcher)
            tool_paths.extend((Path(launcher).resolve(), Path(executable).resolve()))
        result["tool_files_before"] = {str(path): sha(path) for path in tool_paths}
        result.update(produce(directory / "fresh", audit, deadline, result["producer_inventories"]))
        write(directory / "partial.json", result)
        result["replay_process"] = bounded_replay(directory, result, owner, audit, deadline)
        result["tool_files_after"] = {str(path): sha(path) for path in tool_paths}
        result["checks"].update(
            sixteen_historical_pairs_rejected=sum(len(row["pairs"]) for row in result["historical_rejections"]) == 16,
            thirty_two_sidecar_rejections=sum(row["sidecar_rejections"] for row in result["historical_rejections"]) == 32,
            sixteen_projection_rejections=sum(row["projection_rejections"] for row in result["historical_rejections"]) == 16,
            two_fresh_conditional_fixtures=len(result["producers"]) == 2,
            sixty_admitted_native_phases=len(audit.events) == len(audit.results) == 60,
            fresh_process_solver_free=result["replay_process"]["status"] == "passed",
            one_bounded_replay_helper=len(audit.replay_launches.events) == len(audit.replay_results) == 1,
            installed_tools_unchanged=result["tool_files_before"] == result["tool_files_after"],
            historical_and_lookup_solver_free=all(row["kind"] == "git" for row in audit.processes.events
                if row["stage"] in {"historical", "lookup", "publish", "prepare"}))
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if deadline is not None:
            deadline.close()
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["duckdb_dependency_after"] = duckdb_dependency()
        result["original_after"] = {str(path): original_inventory(path) for path in HISTORICAL}
        result["checks"].update(sources_stable=result["source_pins_before"] == result["source_pins_after"],
            selected_duckdb_dependency_unchanged=result["duckdb_dependency_before"] == result["duckdb_dependency_after"],
            original_databases_cas_sources_unchanged=result.get("original_before") == result["original_after"])
        if owner is not None:
            result["shared_after"] = saved.state_summary(owner.state_path)
            result["checks"].update(shared_config_unchanged=guard._config_bytes(result["shared_after"]["config"]) ==
                guard._config_bytes(envelope["config"]), owned_work_drained=not result["shared_after"]["owned_active_leases"]
                and not result["shared_after"]["owned_waiting_requests"])
        if audit is not None:
            result["launches"], result["lifecycles"] = len(audit.events), len(audit.results)
            result["process_counts"] = dict(Counter(row["kind"] for row in audit.processes.events))
            result["replay_transport_launches"] = len(audit.replay_launches.events)
            result["replay_transport_lifecycles"] = len(audit.replay_results)
            result["audit_sha256"] = {}
            for name, rows in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                    ("process-audit.json", audit.processes.events), ("replay-launch-audit.json", audit.replay_launches.events),
                    ("replay-lifecycle-audit.json", audit.replay_results)):
                write(directory / name, rows)
                result["audit_sha256"][name] = sha(directory / name)
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "result": str(directory / "result.json"),
                      "checks": result["checks"], "elapsed_seconds": result["elapsed_seconds"]}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
