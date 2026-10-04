"""Bounded native single-versus-batch conditional evidence query benchmark.

Build a fresh 8- or 32-unit catalog with real Z3/CVC5 observations, then compare
identical ordered page receipts for 1/8/32 selectors. Lookup is solver-free.
This measures amortization of a complete inventory scan, not sublinear indexing.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

import bench_codebase_restart_safety as saved

base = saved.base
native = saved.frozen
SCHEMA = "codebase-query-many-benchmark@1"


class ProcessAudit(native.ProcessAudit):
    """Keep every event on disk, with bounded in-memory Git samples.

    The inherited audit still classifies and rejects forbidden launches before
    any subprocess starts. Only its diagnostic retention changes. Both the
    event count and pre-compression byte count have finite ceilings.
    """

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.stream = gzip.open(path, "xb")
        self.records = 0
        self.raw_bytes = 0
        self.max_records = 131072
        self.max_bytes = 128 * 1024**2
        self.git_samples = Counter()

    def observe(self, event, arguments):
        if event != "subprocess.Popen":
            return
        before = len(self.events)
        try:
            super().observe(event, arguments)
        finally:
            # Inherited refusal appends its event before raising. Preserve that
            # evidence too, while never suppressing the refusal.
            if len(self.events) > before:
                row = self.events[-1]
                raw = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
                base.require(self.records < self.max_records and len(raw) <= 64 * 1024
                    and self.raw_bytes + len(raw) <= self.max_bytes, "compressed audit ledger input bound exceeded")
                self.stream.write(raw)
                self.records += 1
                self.raw_bytes += len(raw)
                if row["kind"] == "git":
                    self.git_samples[row["stage"]] += 1
                    if self.git_samples[row["stage"]] > 32:
                        self.events.pop()

    def finish(self):
        self.stream.close()
        digest = hashlib.sha256()
        with self.path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"counts": self.counts, "events": self.events,
            "events_scope": "all non-Git events and first 32 Git events per stage; full order in compressed ledger",
            "ledger": {"path": str(self.path), "sha256": digest.hexdigest(),
                "records": self.records, "uncompressed_bytes": self.raw_bytes,
                "max_records": self.max_records, "max_uncompressed_bytes": self.max_bytes,
                "compressed_bytes": self.path.stat().st_size}}


def pins():
    paths = [Path(__file__).resolve(), base.ACCELERATE /
        "ipfs_accelerate_py/agent_supervisor/planning/conditional_codebase_batch.py"]
    return {**saved.pins(), **{str(path): base.digest(path.read_bytes()) for path in paths}}


def units(count):
    base.require(type(count) is int and count in {8, 32}, "only reviewed finite fixture sizes are supported")
    return tuple(base.FixtureUnit(f"unit_{i:02d}.py", i + 1,
        i + 2 if i % 8 == 6 else i + 1, "False" if i % 8 == 7 else "True",
        "recorded_conditional_refuted" if i % 8 == 6 else
        "recorded_conditional_vacuous" if i % 8 == 7 else "recorded_conditional_proved")
        for i in range(count))


def requests_for(identities, count):
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
        CodebaseVerificationQueryRequest, CodebaseVerificationSelector,
    )
    requests = []
    for number in range(count):
        row = identities[number % len(identities)]
        selector = (CodebaseVerificationSelector(canonical_key_id=row["key_id"]) if number % 3 == 0 else
            CodebaseVerificationSelector(dependency_kind="source", dependency_value=row["source_cid"])
            if number % 3 == 1 else CodebaseVerificationSelector(path=row["path"], contract_id=row["contract_id"]))
        requests.append(CodebaseVerificationQueryRequest(selector, page_size=1))
    return tuple(requests)


@contextmanager
def measured_calls(catalog):
    """Count actual calls while forwarding unchanged arguments and results."""
    counters = {"resource_envelopes": 0, "inventory_validations": 0, "projection_replays": 0}
    replacements = []
    for target, name, key in ((catalog, "_resources", "resource_envelopes"),
            (catalog._queries, "validate_inventory", "inventory_validations"),
            (catalog, "_read", "projection_replays")):
        original = getattr(target, name)
        def counted(*args, _original=original, _key=key, **kwargs):
            counters[_key] += 1
            return _original(*args, **kwargs)
        setattr(target, name, counted)
        replacements.append((target, name, original))
    try:
        yield counters
    finally:
        for target, name, original in replacements:
            setattr(target, name, original)


def measure(catalog, repository, head, requests, deadline, *, batched):
    started = time.perf_counter()
    with measured_calls(catalog) as counts:
        if batched:
            pages = catalog.query_many_current(repository, expected_head=head,
                requests=requests, **deadline.options())
        else:
            pages = tuple(catalog.query_current(repository, expected_head=head,
                selector=request.selector, page_size=request.page_size, cursor=request.cursor,
                **deadline.options()) for request in requests)
    seconds = time.perf_counter() - started
    values = [page.to_dict() for page in pages]
    base.require(len(values) == len(requests), "query omitted a requested page")
    for page in pages:
        base.require(page.complete and len(page.entries) == 1, "exact fixture selector must return a singleton")
        base.assert_authority(page.entries[0].projection)
    return {"seconds": seconds, "calls": counts, "pages": values}


def compare(catalog, directory, head, identities, audit, deadline, rounds):
    measurements = []
    for round_number in range(rounds):
        for count in (1, 8, 32):
            requests = requests_for(identities, count)
            order = ("individual", "batch") if (round_number + count) % 2 else ("batch", "individual")
            row = {"round": round_number, "selectors": count, "order": list(order)}
            for mode in order:
                with audit.scope("lookup", only_git=True):
                    row[mode] = measure(catalog, directory / "source", head, requests, deadline,
                                        batched=mode == "batch")
            base.require(row["individual"]["pages"] == row["batch"]["pages"], "batch page bytes differ")
            base.require(row["individual"]["calls"] == {"resource_envelopes": count,
                "inventory_validations": count, "projection_replays": count}, "individual work count differs")
            base.require(row["batch"]["calls"] == {"resource_envelopes": 1,
                "inventory_validations": 1, "projection_replays": min(count, len(identities))},
                "batch did not amortize inventory/replay work")
            row["observed_speedup"] = row["individual"]["seconds"] / row["batch"]["seconds"]
            measurements.append(row)
    return measurements


def produce(directory, report, count, owner, audit, deadline):
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
    from ipfs_datasets_py.logic.software_contracts.codebase_verification import verify_current_codebase_unit
    from ipfs_datasets_py.logic.software_contracts.codebase_applicability import verify_current_codebase_applicability
    repository = directory / "source"
    repository.mkdir()
    for unit in units(count):
        (repository / unit.path).write_bytes(unit.source)
    with audit.scope("fixture"):
        for args in (("init", "-q"), ("config", "user.name", "Batch Query Fixture"),
                     ("config", "user.email", "fixture@example.invalid"), ("add", "."), ("commit", "-qm", "fixture")):
            subprocess.run(["git", "-C", str(repository), *args], capture_output=True, check=True, timeout=10)
    index, catalog, connection = base.open_index(directory)
    try:
        with audit.scope("prepare"):
            head = index.prepare_current(repository, repository_id=base.VIEW, operation_id="initial",
                expected_head=None, **deadline.options()).head
        report.update(head=head.to_dict(), producers=[], identities=[])
        for number, unit in enumerate(units(count)):
            base.progress(directory, report, "produce:" + unit.path)
            contract, domain = unit.native()
            started = time.perf_counter()
            with audit.scope("verification"):
                verification = verify_current_codebase_unit(index, repository, expected_head=head,
                    path=unit.path, contracts=[contract], **deadline.options())
            with audit.scope("applicability"):
                applicability = verify_current_codebase_applicability(index, repository, expected_head=head,
                    verification_cid=verification.artifact_cid, domains=[domain], **deadline.options())
            with audit.scope("publish", only_git=True):
                projection = catalog.publish(repository, expected_head=head, verification_cid=verification.artifact_cid,
                    applicability_cid=applicability.artifact_cid, operation_id=f"publish:{number}", **deadline.options())
            value, app = projection.to_dict(), applicability.to_dict()
            selected = value["contracts"][0]
            observations = verification.to_dict()["process_observations"] + app["process_observations"]
            phases = [phase for observation in observations for phase in observation["execution"]["phases"]]
            base.require(len(observations) == 10 and len(phases) == 30, "native observation inventory differs")
            base.require(all(phase["returncode"] == 0 and phase["workspace_cleaned"] and not phase["error"]
                and not any(phase[name] for name in ("timed_out", "cancelled", "resource_exhausted", "output_truncated", "unavailable"))
                and phase["limits"]["memory_bytes"] == phase["limits"]["resident_memory_bytes"] == 128 * 1024**2
                for phase in phases), "native phase escaped clean bounded profile")
            base.require(applicability.conditional_proved is (number % 8 < 6)
                and applicability.conditional_refuted is (number % 8 == 6), "conditional control differs")
            base.require(app["contract_results"][0]["status"] == ("empty_domain" if number % 8 == 7 else "established"),
                "requested-domain control differs")
            report["producers"].append({"path": unit.path, "seconds": time.perf_counter() - started,
                "observations": observations, "applicability_status": app["contract_results"][0]})
            report["identities"].append({"path": unit.path, "contract_id": contract.contract_id,
                "contract_cid": cid_for_structured(contract.to_dict()), "domain_id": domain.domain_id,
                "domain_cid": cid_for_structured(domain.to_dict()), "verification_cid": verification.artifact_cid,
                "source_cid": value["source_binding"]["entry"]["source_cid"], "projection_cid": projection.projection_cid,
                "key_id": selected["canonical_keys"][0]["key_id"]})
            base.require(not base.own_leases(owner), "producer leaked an owned lease")
        return index, catalog, connection, head
    except BaseException:
        connection.close()
        raise


def replay(request_path, config_path):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
        CodebaseVerificationQueryRequest, CodebaseVerificationSelector, CodebaseVerificationQueryCursor,
    )
    request = saved.read_json(request_path, 8 * 1024**2)
    owner, _ = saved.install_saved_owner(config_path)
    base.require(pins() == request["source_pins"], "fresh-process source generation differs")
    audit = ProcessAudit(Path(request["directory"]) / "restart-process-audit.jsonl.gz")
    sys.addaudithook(audit.observe)
    deadline = base.Deadline(180, 120)
    directory = Path(request["directory"])
    index, catalog, connection = base.open_index(directory)
    try:
        head = CodebaseHead.from_dict(request["head"])
        with audit.scope("lookup", only_git=True):
            result = measure(catalog, directory / "source", head,
                requests_for(request["identities"], 32), deadline, batched=True)
            resumed = catalog.query_many_current(directory / "source", expected_head=head,
                requests=(CodebaseVerificationQueryRequest(CodebaseVerificationSelector(), page_size=3,
                    cursor=CodebaseVerificationQueryCursor.from_dict(request["cursor"])),), **deadline.options())[0]
        base.require(result["pages"] == request["pages"], "cold batch receipts differ")
        base.require(resumed.to_dict() == request["resumed_page"], "serialized cursor changed after restart")
        base.require(not base.own_leases(owner), "cold reader leaked owned leases")
        base.require(pins() == request["source_pins"], "fresh-process source changed during lookup")
        return {"completed": True, "measurements": result, "resumed_page": resumed.to_dict(),
            "source_pins": pins(), "process_audit": audit.finish(),
            "saved_pool_after": saved.state_summary(owner.state_path)}
    finally:
        connection.close()
        deadline.close()
        audit.stream.close()


def controls(catalog, connection, repository, head, identities, deadline):
    from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalogError
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
    requests = requests_for(identities, 1)
    # Corruption of an unselected row must still refuse the entire batch.
    original_path = identities[-1]["path"]
    connection.execute("UPDATE codebase_verification_query.entries SET path=? WHERE path=?",
                       ["hidden.py", original_path])
    try:
        try:
            catalog.query_many_current(repository, expected_head=head, requests=requests, **deadline.options())
        except CodebaseVerificationCatalogError:
            pass
        else:
            raise AssertionError("unselected corrupt inventory row escaped validation")
    finally:
        connection.execute("UPDATE codebase_verification_query.entries SET path=? WHERE path=?", [original_path, "hidden.py"])
    source = repository / identities[0]["path"]
    original = source.read_bytes()
    source.write_bytes(original + b"# changed source\n")
    try:
        try:
            catalog.query_many_current(repository, expected_head=head, requests=requests, **deadline.options())
        except StaleCodebaseError:
            pass
        else:
            raise AssertionError("source drift did not refuse the batch")
    finally:
        source.write_bytes(original)
    catalog.query_many_current(repository, expected_head=head, requests=requests, **deadline.options())
    return {"unselected_inventory_corruption_refused": True, "source_drift_refused": True,
            "restored_source_and_inventory_revalidated": True}


def planner_check(catalog, index, repository, head, count, deadline):
    from ipfs_accelerate_py.agent_supervisor.planning.conditional_codebase_batch import match_conditional_codebase_requirements
    from ipfs_accelerate_py.agent_supervisor.planning.conditional_codebase_evidence import match_conditional_codebase_intent
    requirements = []
    for number, statement in ((0, "mathematical-goal"), (6, "mathematical-goal"),
                              (7, "mathematical-goal"), (0, "runtime-goal")):
        unit = units(count)[number]
        contract, domain = unit.native()
        text, document = base.authored_intent(unit, contract, domain)
        requirements.append({"requirement_id": f"request-{len(requirements)}",
            "intent_document": document, "source_text": text, "path": unit.path,
            "contract": contract, "domain": domain, "statement_id": statement})
    individual = []
    for requirement in requirements:
        individual.append(match_conditional_codebase_intent(catalog=catalog, index=index,
            repository=repository, repository_id=head.repository_id, expected_head=head,
            **{key: value for key, value in requirement.items() if key != "requirement_id"}, **deadline.options()))
    with measured_calls(catalog) as counts:
        batch = match_conditional_codebase_requirements(catalog=catalog, index=index,
            repository=repository, repository_id=head.repository_id, expected_head=head,
            requirements=tuple(requirements), **deadline.options())
    base.require(counts == {"resource_envelopes": 1, "inventory_validations": 1, "projection_replays": 3},
                 "supervisor batch did not use one bounded native query")
    base.require([row["match"] for row in batch["matches"]] == individual,
                 "batch supervisor matches differ from individual native matches")
    base.require([row["match"]["status"] for row in batch["matches"]] ==
        ["recorded_conditional_proved", "recorded_conditional_refuted", "recorded_conditional_vacuous", "unknown"],
        "supervisor conditional controls differ")
    base.require(len(batch["residual_requirements"]) == 8, "batch lost unresolved authored requirements")
    base.require(all(batch[name] is False for name in ("admission_authority", "proof_authority",
        "runtime_behavior_verified", "behavioral_satisfaction", "completion_authority")), "batch promoted authority")
    return {"calls": counts, "batch": batch, "individual_matches": individual,
            "identical_matches": True, "all_residuals_retained": True}


def run(directory, report, *, count, rounds, seconds):
    from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
        CodebaseVerificationQueryRequest, CodebaseVerificationSelector,
    )
    config = directory / "saved-scheduler-config.json"
    saved.capture_config(config)
    owner, envelope = saved.install_saved_owner(config)
    report.update(source_pins_before=pins(), runtime=saved.runtime(),
        saved_pool_before=saved.state_summary(owner.state_path), configuration={"units": count,
        "rounds": rounds, "selector_counts": [1, 8, 32], "duckdb": base.DB_CONFIG,
        "overall_timeout_seconds": seconds, "saved_config": envelope["config"]})
    saved.write_json(directory / "command.json", {"argv": [sys.executable, *sys.argv],
        "source_pins": pins(), "cwd": str(Path.cwd())})
    audit = ProcessAudit(directory / "process-audit.jsonl.gz")
    sys.addaudithook(audit.observe)
    deadline = base.Deadline(seconds, 120)
    telemetry = base.Telemetry(owner)
    telemetry.thread.start()
    connection = None
    try:
        index, catalog, connection, head = produce(directory, report, count, owner, audit, deadline)
        base.progress(directory, report, "measure")
        report["measurements"] = compare(catalog, directory, head, report["identities"], audit, deadline, rounds)
        with audit.scope("lookup", only_git=True):
            report["supervisor"] = planner_check(catalog, index, directory / "source", head, count, deadline)
            page = catalog.query_many_current(directory / "source", expected_head=head,
                requests=(CodebaseVerificationQueryRequest(CodebaseVerificationSelector(), page_size=3),), **deadline.options())[0]
            resumed = catalog.query_many_current(directory / "source", expected_head=head,
                requests=(CodebaseVerificationQueryRequest(CodebaseVerificationSelector(), page_size=3,
                    cursor=page.next_cursor),), **deadline.options())[0]
        connection.close()
        connection = None
        request_path = directory / "restart-request.json"
        saved.write_json(request_path, {"directory": str(directory), "head": head.to_dict(),
            "identities": report["identities"], "source_pins": pins(), "cursor": page.next_cursor.to_dict(),
            "resumed_page": resumed.to_dict(), "pages": report["measurements"][-1]["batch"]["pages"]})
        base.progress(directory, report, "fresh_process")
        with audit.scope("restart_launcher"):
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(request_path),
                "--pinned-config", str(config)], capture_output=True, text=True,
                timeout=min(190, deadline.end - time.monotonic()))
        (directory / "restart.stdout").write_text(child.stdout)
        (directory / "restart.stderr").write_text(child.stderr)
        base.require(child.returncode == 0, "cold batch lookup failed: " + child.stderr[-3000:])
        report["restart"] = json.loads(child.stdout.splitlines()[-1])
        index, catalog, connection = base.open_index(directory)
        with audit.scope("controls", only_git=True):
            report["controls"] = controls(catalog, connection, directory / "source", head, report["identities"], deadline)
        report["completed"] = True
    finally:
        if connection is not None:
            connection.close()
        deadline.close()
        report["telemetry"] = telemetry.finish()
        report["source_pins_after"] = pins()
        report["process_audit"] = audit.finish()
        report["saved_pool_after"] = saved.state_summary(owner.state_path)
        report["owned_leases_at_return"] = base.own_leases(owner)
        phases = [phase for producer in report.get("producers", []) for observation in producer["observations"]
                  for phase in observation["execution"]["phases"]]
        counts = dict(Counter(phase["kind"] for phase in phases))
        report["native_phase_counts"] = counts
        report["checks"] = {"completed": report.get("completed") is True,
            "all_native_units": len(report.get("producers", [])) == count,
            "selected_sources_unchanged": report["source_pins_before"] == report["source_pins_after"],
            "version_launches_match_receipts": counts.get("version") == count * 10 ==
                sum(value for key, value in audit.counts.items() if key.endswith(":version")),
            "query_launches_match_receipts": sum(value for key, value in counts.items() if key != "version") == count * 20 ==
                sum(value for key, value in audit.counts.items() if key.endswith(":solver_query")),
            "lookup_solver_free": all(event["kind"] == "git" for event in audit.events if event["stage"] in {"lookup", "controls", "publish"}),
            "cold_batch_and_cursor_replay": report.get("restart", {}).get("completed") is True,
            "all_comparisons_completed": len(report.get("measurements", [])) == rounds * 3,
            "supervisor_batch_matches_and_residuals": report.get("supervisor", {}).get("identical_matches") is True
                and report.get("supervisor", {}).get("all_residuals_retained") is True,
            "integrity_and_source_controls": all(report.get("controls", {}).values()) and len(report.get("controls", {})) == 3,
            "saved_pool_unchanged": report["saved_pool_after"]["config"] == envelope["config"],
            "own_leases_drained": not report["owned_leases_at_return"],
            "telemetry_healthy_and_stopped": not report["telemetry"]["errors"] and report["telemetry"]["sampler_stopped"],
            "overall_deadline_respected": time.monotonic() < deadline.end}
        base.progress(directory, report, "complete" if report.get("completed") else "failed")
    base.require(all(report["checks"].values()), "final batch benchmark checks failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--units", type=int, choices=(8, 32), default=8)
    parser.add_argument("--rounds", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--overall-timeout", type=float, default=1200)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--pinned-config", type=Path)
    args = parser.parse_args()
    sys.path[:0] = [str(base.ACCELERATE), str(base.ROOT)]
    if args.replay:
        base.require(args.pinned_config is not None, "cold replay requires captured shared config")
        print(json.dumps(replay(args.replay, args.pinned_config)))
        return 0
    base.require(args.output is not None and 0 < args.overall_timeout <= 1800, "fresh output and bounded deadline required")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = {"schema": SCHEMA, "started_at_utc": datetime.now(timezone.utc).isoformat(), "completed": False,
              "errors": [], "scope": {"hard_aggregate_cgroup_memory": False, "sublinear_index": False,
                  "runtime_behavior_verified": False, "new_proof_authority": False}}
    started = time.perf_counter()
    try:
        run(directory, report, count=args.units, rounds=args.rounds, seconds=args.overall_timeout)
    except BaseException as error:
        report["completed"] = False
        report["errors"].append({"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()})
    finally:
        report["wall_seconds"] = time.perf_counter() - started
        saved.write_json(directory / "result.json", report)
    print(json.dumps({"result": str(directory / "result.json"), "completed": report["completed"],
                      "wall_seconds": report["wall_seconds"], "checks": report.get("checks", {}), "errors": report["errors"]}))
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
