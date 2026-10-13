"""Independent metadata review of one exact split-feature cell.

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
OLD = N.parent / "legal-permission-retention-20261012-01"
RUN = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01")
LEDGER = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json")
SCHEDULER = Path("/tmp/ipfs-datasets-resource-scheduler-1000.json")
CELLS = ("split-features",)
FORBIDDEN_PACKETS = {
    N.parent / "legal-targeted-loss-20261012-01/authored-reference-packet-v01.json",
    N.parent / "legal-matched-curriculum-20261012-01/authored-reference-packet-v01.json",
}
METADATA_FUNCTIONS = {"require", "canonical", "digest", "schedule", "validate_plan"}
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
    require(path not in {LEDGER, SCHEDULER}, "only private captured endpoint bodies may be parsed")
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
    raw = runner.read_bytes()
    require(len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"]
            and pin(runner) == expected, "consumed qualified runner source differs")
    tree = ast.parse(raw)
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
    namespace = dict(constants, __file__=str(runner), F=N, N2=N.parent / "legal-targeted-loss-20261012-01", RUN_ROOT=RUN,
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
        if event in {"os.chmod", "os.chown", "os.truncate", "os.utime", "os.link", "os.symlink"}:
            require(event == "os.chmod" and Path(args[0]).absolute() == output and args[1] == 0o444,
                    "only owned review freeze chmod allowed")
    return audit


def approved_source(path, artifacts):
    review = read(path)
    if path.name == "root-science-source-independent-review-v01.json":
        require(review["schema"] == "split-feature-root-science-source-independent-review/v1"
                and review["status"] == "PASS", "clean exact root science approval required")
    else:
        expected_schema = {
            "trainer-source-independent-review-v01.json": "split-feature-trainer-source-independent-review/v1",
            "cell-review-helper-independent-review-v02.json": "split-cell-review-helper-source-independent-review/v1",
        }
        require(path.name in expected_schema and review["schema"] == expected_schema[path.name]
                and review["passed"] is True, "clean exact independent approval required")
    require(review["findings"] == [] and type(review["artifacts"]) is dict and review["artifacts"],
            "clean nonempty source artifact closure required")
    for source, expected in review["artifacts"].items():
        require(source not in {str(LEDGER), str(SCHEDULER)} and source not in {str(p) for p in FORBIDDEN_PACKETS},
                "source review must bind only immutable permitted artifacts")
        require(type(expected) is dict and set(expected) in ({"bytes", "sha256"}, {"path", "bytes", "sha256"})
                and ("path" not in expected or expected["path"] == source), "closed consistent review descriptor required")
        brief = {k: expected[k] for k in ("bytes", "sha256")}
        require(pin(source) == brief, "qualified source/review dependency changed")
        require(source not in artifacts or artifacts[source] == brief, "conflicting qualified source identity")
        artifacts[source] = brief
    artifacts[str(path)] = READ_PINS[str(path)]
    return review


def review(cell):
    require(cell in CELLS, "registered selected cell required")
    output = N / (cell + "-training-protocol-independent-review-v01.json")
    require(not os.path.lexists(output), "fresh exclusive review required")
    sys.addaudithook(audit_for(output))
    plan_path = N / (cell + "-plan-v01.json")
    compatibility_path = N / "pre-admission-check-v03.json"
    phase_sample_path = N / "phase-opening-sample-v02.json"
    runner, guardian = N / "run_split_features.py", N / "run_scope_guardian.py"
    registration_path = N / "registration-v01.json"
    baseline_path = N / "resource-baseline-audit-design-v01.json"
    helper_review_path = N / "cell-review-helper-independent-review-v02.json"
    plan, registration, baseline = read(plan_path), read(registration_path), read(baseline_path)
    artifacts = {}
    science_review = approved_source(N / "root-science-source-independent-review-v01.json", artifacts)
    trainer_review = approved_source(N / "trainer-source-independent-review-v01.json", artifacts)
    helper_review = approved_source(helper_review_path, artifacts)
    require(artifacts.get(str(runner)) == pin(runner)
            and artifacts.get(str(Path(__file__).resolve())) == pin(Path(__file__).resolve()),
            "exact independently qualified runner/guardian/review helper required")
    require(pin(guardian)["sha256"] == "10c7c7350a7dbb564ab0fb1299c905020f874c212765afb86d3c1752105184ed",
            "unchanged guardian required")
    require(READ_PINS[str(baseline_path)] == dict(bytes=70534,
            sha256="15995dc220ac449e6ce667d28f7728a3be5ba3b30b515914b73d1c77378d9cb5")
            and baseline["unchanged_guardian"] == dict(path=str(guardian), **pin(guardian)),
            "exact qualified baseline and unchanged N4 guardian required")
    artifacts[str(guardian)] = pin(guardian)
    predicates = metadata_predicates(runner, artifacts[str(runner)])
    predicates["validate_plan"](plan)
    require(plan["cell"] == dict(id=cell, trainable_parameter_policy=cell, actor_ranking_enabled=False,
            presence_ce_weight=1, modality_loss_weight=2)
            and plan["attempt_name"] == "split-feature-20261013-" + cell + "-01", "exact selected cell/attempt differs")
    require(baseline["passed"] is True and baseline["findings"] == []
            and baseline["execution_approval"] is False
            and baseline["baseline_ledger"]["record_count"] == 528, "qualified original528 baseline required")
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
    required_new = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_split_features"
    require(set(plan["source_owner_pins"]) == set(old_owners) | {required_new}, "closed old32+new1 producer closure required")
    for name, old in old_owners.items():
        current = plan["source_owner_pins"][name]
        require(Path(current["path"]).relative_to(N / "datasets") == Path(old["path"]).relative_to(OLD / "datasets")
                and {k: current[k] for k in ("bytes", "sha256")} == {k: old[k] for k in ("bytes", "sha256")},
                "existing science producer changed")
    require(plan["data_export"]["path"] == str(N / "training-export-v01.json")
            and {k: plan["data_export"][k] for k in ("bytes", "sha256")}
            == {k: old_registration["data_export"][k] for k in ("bytes", "sha256")},
            "byte-identical copied N3 export required")
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
    require(tests["passed"] is True and tests["findings"] == [] and tests["tests_passed"] == 194
            and tests["failures"] == tests["errors"] == tests["skipped"] == 0, "actual combined194 pure-test pass required")
    artifacts[str(tests_path)] = READ_PINS[str(tests_path)]
    require(plan["baseline_results"] is None and plan["baseline_plan"] is None,
            "fresh split-feature baseline required")
    parent_reference = plan["parent_capture_reference"]
    require(parent_reference == registration["parent_capture_reference"], "registered parent capture reference differs")
    for descriptor in [parent_reference["freeze"], parent_reference["summary"], *parent_reference["panels"].values()]:
        require(pin(descriptor["path"]) == {k: descriptor[k] for k in ("bytes", "sha256")}
                == plan["artifacts"][descriptor["path"]], "qualified initial392 capture reference differs")
    phase_sample = read(phase_sample_path)
    require(phase_sample["schema"] == "split-feature-phase-opening-sample/v1"
            and phase_sample["continuous_custody"] is False
            and phase_sample["check"] == dict(path=str(compatibility_path), **pin(compatibility_path)),
            "fresh private opening/check descriptor differs")
    private_paths = {}
    for label, endpoint in (("ledger", LEDGER), ("scheduler", SCHEDULER)):
        sampled = phase_sample["samples"][label]
        private = Path(sampled["private_copy"]["path"])
        require(private == N / "private-runtime-snapshots" / ("phase-opening-" + label + "-v02.json")
                and private.parent.stat().st_mode & 0o777 == 0o700 and private.stat().st_mode & 0o777 == 0o400,
                "exclusive private opening path/mode differs")
        require(sampled["source"] == dict(path=str(endpoint), **pin(endpoint))
                and {k: sampled["private_copy"][k] for k in ("bytes", "sha256")} == pin(private) == pin(endpoint),
                "private opening bytes differ from sampled live endpoint")
        private_paths[label] = private
    compatible = read(compatibility_path)
    require(compatible["passed"] is True and compatible["findings"] == []
            and compatible["resources"] == RESOURCE_CONTRACT
            and compatible["physical_run_root"] == str(RUN), "exact fresh guardian compatibility required")
    require(all(compatible[k] is False for k in ("admission_guaranteed", "reservation_acquired",
            "scheduler_client_constructed", "model_started", "shared_state_modified")), "read-only check required")
    ledger, scheduler = read(private_paths["ledger"]), read(private_paths["scheduler"])
    ledger_pin, scheduler_pin = pin(LEDGER), pin(SCHEDULER)
    require(ledger_pin == {k: compatible["disk_ledger"][k] for k in ("bytes", "sha256")}
            and scheduler_pin == {k: compatible["shared_state"][k] for k in ("bytes", "sha256")},
            "live endpoint differs from fresh check")
    require(ledger["schema"] == baseline["baseline_ledger"]["schema"]
            and ledger["limit_bytes"] == compatible["disk_limit_bytes"] == 145000000000
            and ledger["roots"] == baseline["counted_root_metadata"], "cap/root/schema changed")
    hashes = {identifier: digest(body) for identifier, body in ledger["reservations"].items()}
    original = baseline["baseline_ledger"]["record_body_hashes"]
    require(len(original) == len(hashes) == 528 and hashes == original,
            "original528 body changed or disappeared")
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
    for path in (plan_path, registration_path, runner, guardian, compatibility_path, baseline_path, phase_sample_path,
                 LEDGER, SCHEDULER, Path(__file__).resolve()):
        artifacts[str(path)] = pin(path)
    for source, expected in READ_PINS.items():
        if "private-runtime-snapshots" in Path(source).parts:
            continue
        require(source not in artifacts or artifacts[source] == expected,
                "parsed metadata differs from artifact identity")
        artifacts[source] = expected
    for source, expected in READ_PINS.items():
        require(pin(source) == expected, "closing consumed raw body fence differs")
    for source, expected in artifacts.items():
        require(pin(source) == expected, "closing immutable or live artifact fence differs")
    require(not os.path.lexists(attempt), "attempt appeared before review seal")
    result = dict(schema="split-feature-cell-training-protocol-independent-review/v1", passed=True,
        findings=[], phase="training", observed_at_utc=datetime.now(timezone.utc).isoformat(),
        package_root=plan["package_root"], run_root=str(RUN), plan_sha256=pin(plan_path)["sha256"],
        runner_sha256=pin(runner)["sha256"], guardian_sha256=pin(guardian)["sha256"], artifacts=artifacts,
        selected_cell=plan["cell"], attempt_name=plan["attempt_name"], physical_output=str(attempt / "results"),
        source_producer_count=len(plan["source_owner_pins"]), first_recipe_artifact_count=len(registration["artifacts"]),
        common_training_manifest_sha256=COMMON_MANIFEST, promotion_gate=plan["promotion_gate"],
        resource_contract=RESOURCE_CONTRACT, original528_unchanged=True,
        opening_ledger=dict(path=str(LEDGER), schema=ledger["schema"], **ledger_pin, record_count=len(hashes),
            record_status_counts=dict(Counter(body["status"] for body in ledger["reservations"].values())),
            full_nonreleased_claim_bytes=claims, record_body_sha256=hashes,
            record_body_hash_map_sha256=digest(hashes), full_record_bodies_published=False,
            limit_bytes=ledger["limit_bytes"], roots=ledger["roots"]),
        opening_scheduler=dict(path=str(SCHEDULER), **scheduler_pin, device=shared.st_dev, inode=shared.st_ino,
            schema_version=scheduler["schema_version"], config_sha256=digest(scheduler["config"]),
            config=scheduler["config"], lease_count=0, waiter_count=0), run_root_identity=baseline["run_root_identity"],
        reused_baseline_summary=None, parent_capture_reference=parent_reference, initial392_preupdate_runtime_parity_required=True,
        phase_opening_sample=dict(path=str(phase_sample_path), **READ_PINS[str(phase_sample_path)]), schedule=prepared,
        scope="Independent exact one-cell source/metadata review; original528 and every fresh opening body bound; no admission performed",
        next_step_scope="One unchanged guardian invocation for this exact selected cell and absent attempt, subject to fresh admission/proof-safety/owner capacity gates.",
        reviewer_actions=dict(full_module_imports=0, numerical_imports=0, model_state_JSON_parses=0,
            evaluation_reference_packet_reads_or_scores=0, models_restores_forwards_updates=0,
            resource_API_lease_lock_calls=0, shared_tree_censuses=0, network_compiler_Git_HF_calls=0),
        limitations=[
            "Source and fake contract tests do not establish actual numerical completion, parameter freezing, optimizer moments or modality retention; initial392 complete-score parity before updates and actual returned32 trace/final392 modality vectors remain required.",
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
