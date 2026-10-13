"""Independent metadata review of one exact permission-retention cell.

No package, model, resource client or reference packet is imported. This
observer extracts only separately qualified metadata predicates from exact
runner source, and writes one exclusive review granting no reservation.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import sys

N = Path(__file__).resolve().parent
OLD = N.parent / "legal-targeted-loss-20261012-01"
RUN = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01")
LEDGER = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json")
SCHEDULER = Path("/tmp/ipfs-datasets-resource-scheduler-1000.json")
CELLS = ("all-parameters", "span-heads-only")
FORBIDDEN_PACKETS = {
    OLD / "authored-reference-packet-v01.json",
    N.parent / "legal-matched-curriculum-20261012-01/authored-reference-packet-v01.json",
}
METADATA_FUNCTIONS = {"require", "canonical", "digest", "schedule", "validate_plan", "reuse_baseline"}
LITERAL_CONSTANTS = {"PLAN_FIELDS", "SCHEMA", "RETAINED_FORBIDDEN", "HELPER_SHA"}
RESOURCE_CONTRACT = dict(cpu_slots=2, memory_mb=1536, child_process_slots=1, storage_bytes=200000000,
                         child_deadline_seconds=300, admission_timeout_seconds=120, ledger_lock_timeout_seconds=60)
COMMON_MANIFEST = "afa0deeebf4052831883c046104a8808342b67a7c8dc2e58de2f9208a9287c34"
READ_PINS = {}
sys.dont_write_bytecode = True


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(),
            "canonical absolute ordinary artifact required")
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= 128 * 1024 * 1024,
            "bounded regular artifact required")
    data = path.read_bytes()
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and len(data) == before.st_size, "artifact changed while reading")
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read(path):
    path = Path(path)
    require(path not in FORBIDDEN_PACKETS and "reference-packet" not in path.name,
            "authored reference packet forbidden")
    require("checkpoint" not in path.name, "model-state JSON parsing forbidden")
    expected = pin(path)
    require(expected["bytes"] <= 16 * 1024 * 1024, "bounded metadata JSON required")
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected["sha256"] and pin(path) == expected,
            "metadata changed while reading")
    key = str(path)
    require(key not in READ_PINS or READ_PINS[key] == expected,
            "previously parsed metadata identity changed")
    READ_PINS[key] = expected

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate metadata key")
            result[key] = value
        return result

    def finite(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite metadata number")
        return result

    return json.loads(data, object_pairs_hook=unique, parse_float=finite,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def metadata_predicates(runner, expected):
    require(pin(runner) == expected, "qualified runner differs")
    tree = ast.parse(runner.read_text(encoding="utf-8"))
    nodes = [copy.deepcopy(node) for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in METADATA_FUNCTIONS]
    require({node.name for node in nodes} == METADATA_FUNCTIONS, "missing metadata predicate")
    for node in nodes:
        require(not node.decorator_list and not any(isinstance(child, (ast.Import, ast.ImportFrom))
                for child in ast.walk(node)), "metadata extraction refuses imports/decorators")
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in LITERAL_CONSTANTS:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    require(set(constants) == LITERAL_CONSTANTS, "missing closed metadata constants")
    namespace = dict(constants, __file__=str(runner), F=N, N2=OLD, RUN_ROOT=RUN,
        HELPER=N.parent / "legal-temporal-binding-20261012-01/run_temporal_contrast_pilot.py",
        Path=Path, math=math, random=random, json=json, hashlib=hashlib, read=read,
        pin=lambda path: {"path": str(Path(path)), **pin(path)})
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(runner), "exec"), namespace)
    return namespace


def audit_for(output):
    def audit(event, args):
        if event == "import" and args[0].split(".")[0] in {
                "torch", "numpy", "transformers", "sentence_transformers", "ipfs_datasets_py"}:
            raise ValueError("production/numerical import forbidden")
        if event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn")) or event in {
                "os.system", "os.fork", "os.posix_spawn", "os.kill", "os.killpg", "fcntl.flock",
                "os.remove", "os.rmdir", "os.mkdir", "os.rename", "os.replace", "os.unlink"}:
            raise ValueError("process/network/lock/mutation forbidden")
        if event == "open":
            path, mode, flags = args
            if isinstance(path, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(path)).absolute()
                require(path not in FORBIDDEN_PACKETS and "reference-packet" not in path.name,
                        "authored reference packet forbidden")
            write = isinstance(mode, str) and any(c in mode for c in "wax+")
            write |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT
                                                             | os.O_TRUNC | os.O_APPEND))
            require(not write or path == output, "only exclusive owned review may be written")
        if event == "os.chmod":
            require(Path(args[0]).absolute() == output, "only owned review chmod allowed")
    return audit


def approved_source(path, artifacts):
    review = read(path)
    require(review["passed"] is True and review["findings"] == []
            and type(review["artifacts"]) is dict and review["artifacts"], "clean independent source review required")
    for source, expected in review["artifacts"].items():
        require(source not in {str(LEDGER), str(SCHEDULER)} and source not in {str(p) for p in FORBIDDEN_PACKETS},
                "source review must bind only immutable permitted artifacts")
        require(pin(source) == expected, "qualified source/review dependency changed")
        require(source not in artifacts or artifacts[source] == expected, "conflicting qualified source identity")
        artifacts[source] = expected
    artifacts[str(path)] = READ_PINS[str(path)]
    return review


def review(cell):
    require(cell in CELLS, "registered selected cell required")
    output = N / (cell + "-training-protocol-independent-review-v01.json")
    require(not os.path.lexists(output), "fresh exclusive review required")
    sys.addaudithook(audit_for(output))
    plan_path = N / (cell + "-plan-v01.json")
    compatibility_path = N / (cell + "-compatibility-v01.json")
    runner, guardian = N / "run_permission_retention.py", N / "run_scope_guardian.py"
    registration_path = N / "registration-v01.json"
    baseline_path = N / "resource-baseline-audit-design-v01.json"
    helper_review_path = N / "cell-review-helper-independent-review-v01.json"
    plan, registration, baseline = read(plan_path), read(registration_path), read(baseline_path)
    artifacts = {}
    science_review = approved_source(N / "root-science-source-independent-review-v01.json", artifacts)
    trainer_review = approved_source(N / "trainer-source-independent-review-v01.json", artifacts)
    helper_review = approved_source(helper_review_path, artifacts)
    require(artifacts.get(str(runner)) == pin(runner)
            and artifacts.get(str(guardian)) == pin(guardian)
            and artifacts.get(str(Path(__file__).resolve())) == pin(Path(__file__).resolve()),
            "exact independently qualified runner/guardian/review helper required")
    require(pin(guardian)["sha256"] == "10c7c7350a7dbb564ab0fb1299c905020f874c212765afb86d3c1752105184ed",
            "unchanged guardian required")
    predicates = metadata_predicates(runner, artifacts[str(runner)])
    predicates["validate_plan"](plan)
    require(plan["cell"] == dict(id=cell, trainable_parameter_policy=cell, actor_ranking_enabled=False,
            presence_ce_weight=1, modality_loss_weight=2)
            and plan["attempt_name"] == "permission-retention-20261012-" + cell + "-01", "exact selected cell/attempt differs")
    require(baseline["passed"] is True and baseline["findings"] == []
            and baseline["execution_approval"] is False
            and baseline["baseline_ledger"]["record_count"] == 526, "qualified original526 baseline required")
    require(plan["data_export"] == registration["data_export"]
            and plan["source_owner_pins"] == registration["source_owner_pins"], "registered data/producers differ")
    for source, expected in plan["artifacts"].items():
        require(type(expected) is dict and set(expected) == {"bytes", "sha256"}
                and pin(source) == expected, "plan artifact changed")
        require(source not in artifacts or artifacts[source] == expected, "plan/source authority conflict")
        artifacts[source] = expected
    for source, expected in registration["artifacts"].items():
        require(plan["artifacts"].get(source) == expected, "registered immutable artifact missing")
    for name, expected in plan["source_owner_pins"].items():
        require(type(name) is str and name.startswith("ipfs_datasets_py.") and type(expected) is dict
                and set(expected) == {"path", "bytes", "sha256"}
                and Path(expected["path"]).is_relative_to(N / "datasets")
                and pin(expected["path"]) == {k: expected[k] for k in ("bytes", "sha256")}
                and plan["artifacts"].get(expected["path"]) == {k: expected[k] for k in ("bytes", "sha256")},
                "all exact isolated package producer identities required")
    old_registration = read(OLD / "registration-v01.json")
    old_owners = old_registration["source_owner_pins"]
    required_new = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_permission_retention"
    require(set(plan["source_owner_pins"]) == set(old_owners) | {required_new}, "closed old31+new1 producer closure required")
    for name, old in old_owners.items():
        current = plan["source_owner_pins"][name]
        require(Path(current["path"]).relative_to(N / "datasets") == Path(old["path"]).relative_to(OLD / "datasets")
                and {k: current[k] for k in ("bytes", "sha256")} == {k: old[k] for k in ("bytes", "sha256")},
                "existing science producer changed")
    require(plan["data_export"]["path"] == str(N / "training-export-v01.json")
            and {k: plan["data_export"][k] for k in ("bytes", "sha256")}
            == {k: old_registration["data_export"][k] for k in ("bytes", "sha256")},
            "byte-identical copied N2 export required")
    artifacts[str(OLD / "registration-v01.json")] = READ_PINS[str(OLD / "registration-v01.json")]
    data = read(plan["data_export"]["path"])
    require(set(data["training_populations"]) == {"mixed"}
            and len(data["training_populations"]["mixed"]) == 168
            and digest(data["training_populations"]["mixed"]) == plan["training_manifest_sha256"] == COMMON_MANIFEST,
            "exact unchanged common168 training rows required")
    require("authored_eval" not in data["diagnostic_metadata"]
            and len(data["diagnostic_populations"]["authored_eval"]) == 72
            and all(set(row) == {"id", "source_text", "latent"}
                    for row in data["diagnostic_populations"]["authored_eval"]), "evaluation references leaked into child")
    prepared = predicates["schedule"](data["training_populations"]["mixed"], seed=plan["batch_order_seed"])
    require(len(prepared["batch_indices"]) == 32 and all(len(row) == 12 for row in prepared["batch_indices"])
            and prepared["final_progress"] == dict(epochs_completed=2, row_cursor=48, optimizer_steps=32),
            "exact32 returned-batch recipe required")
    tests_path = N / "combined-pure-tests-observation-v01.json"
    tests = read(tests_path)
    require(tests["passed"] is True, "actual combined pure-test pass required")
    artifacts[str(tests_path)] = READ_PINS[str(tests_path)]
    if cell == CELLS[0]:
        require(plan["baseline_results"] is None and plan["baseline_plan"] is None,
                "first cell must create only zero-update parent baseline")
    else:
        first_path = N / (CELLS[0] + "-plan-v01.json")
        first_review_path = N / (CELLS[0] + "-training-protocol-independent-review-v01.json")
        first, first_review = read(first_path), read(first_review_path)
        require(first_review["passed"] is True and first_review["findings"] == []
                and first_review["phase"] == "training" and pin(first_path)["sha256"] == first_review["plan_sha256"],
                "exact qualified first phase required")
        variable = {"artifacts", "attempt_name", "cell", "baseline_results", "baseline_plan"}
        require(set(plan) == set(first) and all(plan[k] == first[k] for k in set(first) - variable),
                "second scientific/source/resource boundary changed")
        reports = predicates["reuse_baseline"](plan)
        summary_path = Path(plan["baseline_results"]["path"])
        additions = {str(first_path), str(summary_path), str(summary_path.parent.parent / "guardian-exit.json"),
                     str(summary_path.parent.parent / "pre-admission.json")}
        for panel in reports:
            additions.update(panel[k]["path"] for k in ("raw", "joint", "score") if panel[k] is not None)
        require(set(plan["artifacts"]) == set(first["artifacts"]) | additions
                and all(plan["artifacts"].get(p) == v for p, v in first["artifacts"].items()),
                "only explicit authenticated baseline additions allowed")
        for source, expected in first_review["artifacts"].items():
            if source not in {str(LEDGER), str(SCHEDULER)}:
                require(pin(source) == expected, "immutable first qualification changed")
                require(source not in artifacts or artifacts[source] == expected, "first/source authority conflict")
                artifacts[source] = expected
        artifacts[str(first_review_path)] = READ_PINS[str(first_review_path)]
    compatible = read(compatibility_path)
    require(compatible["passed"] is True and compatible["findings"] == []
            and compatible["resources"] == RESOURCE_CONTRACT
            and compatible["physical_run_root"] == str(RUN), "exact fresh guardian compatibility required")
    require(all(compatible[k] is False for k in ("admission_guaranteed", "reservation_acquired",
            "scheduler_client_constructed", "model_started", "shared_state_modified")), "read-only check required")
    ledger, scheduler = read(LEDGER), read(SCHEDULER)
    ledger_pin, scheduler_pin = pin(LEDGER), pin(SCHEDULER)
    require(ledger_pin == {k: compatible["disk_ledger"][k] for k in ("bytes", "sha256")}
            and scheduler_pin == {k: compatible["shared_state"][k] for k in ("bytes", "sha256")},
            "live endpoint differs from fresh check")
    require(ledger["schema"] == baseline["baseline_ledger"]["schema"]
            and ledger["limit_bytes"] == compatible["disk_limit_bytes"] == 145000000000
            and ledger["roots"] == baseline["counted_root_metadata"], "cap/root/schema changed")
    hashes = {identifier: digest(body) for identifier, body in ledger["reservations"].items()}
    original = baseline["baseline_ledger"]["record_body_hashes"]
    require(len(original) == 526 and all(hashes.get(k) == v for k, v in original.items()),
            "original526 body changed or disappeared")
    claims = sum(body["storage_bytes"] for body in ledger["reservations"].values() if body["status"] != "released")
    require(claims == compatible["outstanding_full_reservations_bytes"], "fresh full-claim accounting differs")
    config = baseline["scheduler_observation"]
    require(scheduler["schema_version"] == config["schema_version"]
            and scheduler["config"] == compatible["shared_config"] == config["config"]
            and not scheduler["leases"] and not scheduler["waiters"]
            and compatible["lease_count"] == compatible["waiter_count"] == 0, "scheduler configuration/occupancy changed")
    for root in ledger["roots"] + [baseline["run_root_identity"]]:
        path = Path(root["path"]); observed = path.stat()
        require(path.resolve(strict=True) == path and stat.S_ISDIR(observed.st_mode)
                and (observed.st_dev, observed.st_ino) == (root["device"], root["inode"]), "counted/run-root identity changed")
    shared = SCHEDULER.stat()
    require((shared.st_dev, shared.st_ino) == (compatible["shared_state"]["device"], compatible["shared_state"]["inode"]),
            "fresh scheduler identity drift")
    attempt = RUN / plan["attempt_name"]
    require(not os.path.lexists(attempt) and attempt.resolve() == attempt, "selected attempt already exists")
    resource_sources = {p: v for p, v in baseline["artifacts"].items()
                        if p.startswith("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/")}
    require(len(resource_sources) == len(compatible["producers"]) == 10
            and set(resource_sources) == set(compatible["producers"]), "exact ten resource producer closure required")
    for source, expected in compatible["producers"].items():
        require(pin(source) == resource_sources[source]
                == {k: expected[k] for k in ("bytes", "sha256")}, "resource producer differs")
        artifacts[source] = pin(source)
    for path in (plan_path, registration_path, runner, guardian, compatibility_path, baseline_path,
                 LEDGER, SCHEDULER, Path(__file__).resolve()):
        artifacts[str(path)] = pin(path)
    for source, expected in READ_PINS.items():
        require(source not in artifacts or artifacts[source] == expected,
                "parsed metadata differs from artifact identity")
        artifacts[source] = expected
    for source, expected in artifacts.items():
        require(pin(source) == expected, "closing immutable or live artifact fence differs")
    require(not os.path.lexists(attempt), "attempt appeared before review seal")
    result = dict(schema="permission-retention-cell-training-protocol-independent-review/v1", passed=True,
        findings=[], phase="training", observed_at_utc=datetime.now(timezone.utc).isoformat(),
        package_root=plan["package_root"], run_root=str(RUN), plan_sha256=pin(plan_path)["sha256"],
        runner_sha256=pin(runner)["sha256"], guardian_sha256=pin(guardian)["sha256"], artifacts=artifacts,
        selected_cell=plan["cell"], attempt_name=plan["attempt_name"], physical_output=str(attempt / "results"),
        source_producer_count=len(plan["source_owner_pins"]), first_recipe_artifact_count=len(registration["artifacts"]),
        common_training_manifest_sha256=COMMON_MANIFEST, promotion_gate=plan["promotion_gate"],
        resource_contract=RESOURCE_CONTRACT, original526_unchanged=True,
        opening_ledger=dict(path=str(LEDGER), schema=ledger["schema"], **ledger_pin, record_count=len(hashes),
            record_status_counts=dict(Counter(body["status"] for body in ledger["reservations"].values())),
            full_nonreleased_claim_bytes=claims, record_body_sha256=hashes,
            record_body_hash_map_sha256=digest(hashes), full_record_bodies_published=False,
            limit_bytes=ledger["limit_bytes"], roots=ledger["roots"]),
        opening_scheduler=dict(path=str(SCHEDULER), **scheduler_pin, device=shared.st_dev, inode=shared.st_ino,
            schema_version=scheduler["schema_version"], config_sha256=digest(scheduler["config"]),
            config=scheduler["config"], lease_count=0, waiter_count=0), run_root_identity=baseline["run_root_identity"],
        reused_baseline_summary=plan["baseline_results"], schedule=prepared,
        scope="Independent exact one-cell source/metadata review; original526 and every fresh opening body bound; no admission performed",
        next_step_scope="One unchanged guardian invocation for this exact selected cell and absent attempt, subject to fresh admission/proof-safety/owner capacity gates.",
        reviewer_actions=dict(full_module_imports=0, numerical_imports=0, model_state_JSON_parses=0,
            evaluation_reference_packet_reads_or_scores=0, models_restores_forwards_updates=0,
            resource_API_lease_lock_calls=0, shared_tree_censuses=0, network_compiler_Git_HF_calls=0),
        limitations=[
            "Source and fake contract tests do not establish actual numerical completion, parameter freezing, optimizer moments or modality retention; actual returned32 trace and all392 saved float32 vectors remain required.",
            "Cap/full claims, root identities and empty occupancy are sampled endpoints. Review grants no reservation, headroom or continuous coverage; unchanged guardian performs fresh admission.",
            "Reservations and sampled watchdog evidence are not kernel CPU/memory quotas. Preserve partial attempts, checkpoints and failures; do not retry unknown outcomes.",
            "All panels are exposed authored/shared-template regression evidence; law8 is unreviewed. Disabled384, broader-family, Lake, legal gold and default promotion remain unqualified.",
            "Bitwise modality retention alone does not imply complete IR retention; raw96/96, joint96/96 and zero permission-to-obligation remain separate external gates."])
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    os.chmod(output, 0o444)
    print(json.dumps(dict(path=str(output), **pin(output), passed=True, phase="training"), sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", required=True, choices=CELLS)
    args = parser.parse_args()
    review(args.cell)
