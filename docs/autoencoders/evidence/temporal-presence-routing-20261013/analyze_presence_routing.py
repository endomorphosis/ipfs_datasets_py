"""Fixed saved-score presence ablations; no model execution or checkpoint parsing."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
N4 = ROOT.parent / "legal-split-feature-20261013-01"
N2 = ROOT.parent / "legal-targeted-loss-20261012-01"
T = ROOT.parent / "legal-temporal-binding-20261012-01"
PLAN = ROOT / "diagnostic-plan-v01.json"
OUTPUT = ROOT / "presence-routing-analysis-v01.json"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
PANELS = ("old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval", "authored_dev", "authored_eval", "law")
COUNTS = dict(zip(PANELS, (96, 36, 36, 72, 72, 72, 8), strict=True))
MODALITIES = ("O", "P", "F")
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
EXPECTED = {}
OBSERVED = {}
WRITING = False


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(event, args):
    if event == "import" and args[0].split(".")[0] in {
        "torch", "numpy", "transformers", "sentence_transformers", "ipfs_datasets_py"
    }:
        raise RuntimeError("Numerical and production imports prohibited in saved-score analysis")
    if event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn")) or event in {
        "os.system", "os.fork", "os.posix_spawn", "os.kill", "os.killpg", "fcntl.flock",
        "os.mkdir", "os.remove", "os.rename", "os.replace", "os.rmdir", "os.unlink"
    }:
        raise RuntimeError("No process, network, resource API or filesystem mutation")
    if event in {"os.chmod", "os.chown", "os.truncate", "os.utime", "os.link", "os.symlink"}:
        require(event == "os.chmod" and WRITING and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444,
                "Only the exclusive analysis output may be frozen")
    if event == "open":
        path, mode, flags = args
        writing = isinstance(mode, str) and any(c in mode for c in "wax+")
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        if writing:
            require(WRITING and isinstance(path, (str, bytes, os.PathLike))
                    and Path(os.fsdecode(path)).absolute() == OUTPUT, "Only exclusive output writes permitted")


sys.dont_write_bytecode = True
sys.addaudithook(audit)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path, expected=None):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, "Physical absolute input required")
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode), "Symlink input rejected")
        require(stat.S_ISREG(info.st_mode) if part == path else stat.S_ISDIR(info.st_mode), "Ordinary input required")
    before = path.stat()
    hashed = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            hashed.update(chunk)
    after = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after), "Input drift during hashing")
    actual = dict(bytes=size, sha256=hashed.hexdigest())
    if expected is not None:
        wanted = {k: expected[k] for k in ("bytes", "sha256")}
        require(actual == wanted and ("path" not in expected or expected["path"] == str(path)), "Input pin mismatch")
        require(str(path) not in EXPECTED or EXPECTED[str(path)] == wanted, "Conflicting expected pin")
        EXPECTED[str(path)] = wanted
    require(str(path) not in OBSERVED or OBSERVED[str(path)] == actual, "Input changed since opening")
    OBSERVED[str(path)] = actual
    return dict(path=str(path), **actual)


def read(path, expected=None):
    path = Path(path)
    require("checkpoint" not in path.name and "private-runtime-snapshots" not in path.parts,
            "Checkpoint and private body parsing prohibited")
    value = pin(path, expected)
    require(value["bytes"] <= 16 * 1024 * 1024, "Bounded JSON required")
    raw = path.read_bytes()
    require(len(raw) == value["bytes"] and hashlib.sha256(raw).hexdigest() == value["sha256"], "Consumed bytes changed")

    def unique(items):
        result = {}
        for k, v in items:
            require(k not in result, "Duplicate JSON key")
            result[k] = v
        return result

    def reject(value):
        raise ValueError("Nonfinite JSON: " + value)

    result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    pin(path, value)
    return result


def detached(path, names, namespace):
    path = Path(path)
    require(str(path) in EXPECTED, "Pinned source required before AST extraction")
    value = pin(path, EXPECTED[str(path)])
    require(value["bytes"] < 1024 * 1024, "Bounded source required")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == value["sha256"], "Consumed source drift")
    nodes = [n for n in ast.parse(raw).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    require(len(nodes) == len(names) and {n.name for n in nodes} == set(names), "Exact detached predicate set required")
    require(not any(n.decorator_list for n in nodes), "Decorators prohibited")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    pin(path, value)
    return namespace


def f32(value):
    require(type(value) in (int, float) and math.isfinite(value), "Finite scalar required")
    result = struct.unpack("!f", struct.pack("!f", value))[0]
    require(math.isfinite(result), "Finite float32 required")
    return result


def floats(value):
    if type(value) is dict:
        return b"".join(floats(value[k]) for k in sorted(value))
    if type(value) is list:
        return b"".join(floats(v) for v in value)
    require(type(value) in (float, int) and f32(value) == value, "Exact binary32 score required")
    return struct.pack("!f", value)


def compose(source, parent, trained, fields):
    require(type(fields) is list and fields in ([], ["temporal"], list(FIELDS[2:])), "Fixed field policy required")
    source_sha = hashlib.sha256(source["source_text"].encode()).hexdigest()
    require(source["id"] == parent["id"] == trained["id"] and
            source_sha == parent["source_sha256"] == trained["source_sha256"], "Source identity mismatch")
    require(canonical(parent["scores"]["tokens"]) == canonical(trained["scores"]["tokens"]), "Token geometry mismatch")
    scores = deepcopy(trained["scores"])
    for field in fields:
        scores["presence_logits"][field] = deepcopy(parent["scores"]["presence_logits"][field])
    for field in FIELDS[2:]:
        owner = parent if field in fields else trained
        require(floats(scores["presence_logits"][field]) == floats(owner["scores"]["presence_logits"][field]),
                "Presence component drift")
    for field in ("modality_logits", "start_logits", "end_logits"):
        require(floats(scores[field]) == floats(trained["scores"][field]), "Retained learned component drift")
    return dict(id=source["id"], source_sha256=source_sha, scores=scores)


def permission_summary(rows, raw, selected):
    result = {view: dict(P_to_P=0, P_to_O=0, P_to_F=0, P_abstentions=0)
              for view in ("head", "greedy", "joint")}
    for source, occurrence, greedy_row, joint_row in zip(rows, raw["occurrences"], raw["inference"]["rows"], selected, strict=True):
        if source["canonical_ir"]["rules"][0]["modality"] != "P":
            continue
        choice, margin = JOINT["_choice"](occurrence["scores"]["modality_logits"])
        head = MODALITIES[choice] if margin > 1e-7 else None
        modes = dict(head=head,
            greedy=greedy_row["canonical_ir"]["rules"][0]["modality"] if greedy_row["canonical_ir"] else None,
            joint=joint_row["result"]["canonical_ir"]["rules"][0]["modality"] if joint_row["result"]["canonical_ir"] else None)
        for view, mode in modes.items():
            result[view]["P_to_" + mode if mode else "P_abstentions"] += 1
    return result


def compact_score(score):
    return {k: v for k, v in score.items() if k not in ("rows", "schema", "reference_scope", "semantic_accuracy", "used_for_updates_or_selection", *FALSE)}


def differences(before, after):
    require([r["id"] for r in before] == [r["id"] for r in after], "Exact ordered row IDs required")
    return {view + "_" + outcome: [a["id"] for a, b in zip(before, after, strict=True)
            if (a[view + "_exact_ir"] and not b[view + "_exact_ir"]) == (outcome == "regressions")
            and a[view + "_exact_ir"] != b[view + "_exact_ir"]]
            for view in ("raw", "joint") for outcome in ("regressions", "recoveries")}


def main():
    global WRITING, JOINT
    require(not OUTPUT.exists(), "Exclusive new output required")
    plan = read(PLAN)
    require(plan["variants"] == {"parent": None, "split_features": [], "parent_temporal_presence": ["temporal"],
            "parent_all_optional_presence": list(FIELDS[2:])}, "Declared variant set differs")
    for path, descriptor in plan["inputs"].items():
        pin(Path(path), descriptor)
    freeze = read(N4 / "split-feature-output-freeze-v01.json", plan["inputs"][str(N4 / "split-feature-output-freeze-v01.json")])
    prior = read(N4 / "split-feature-result-analysis-v01.json", plan["inputs"][str(N4 / "split-feature-result-analysis-v01.json")])
    for name in ("result-independent-review-v01.json", "runtime-independent-review-v01.json", "final-split-feature-integration-independent-review-v01.json"):
        review = read(N4 / name, plan["inputs"][str(N4 / name)])
        require(review["passed"] is True and review["findings"] == [], "Clean retained review required")
    require(freeze["all_outputs_frozen"] is True and freeze["reference_packet_previously_scored"] is True,
            "Frozen previously exposed inputs required")
    require(prior["passed"] is True and prior["findings"] == [] and prior["default_promotion"] is False, "Qualified N4 analysis required")
    data = read(Path(freeze["training_export"]["path"]), freeze["training_export"])
    registration = read(Path(freeze["registration"]["path"]), freeze["registration"])
    for descriptor in registration["source_owner_pins"].values():
        pin(Path(descriptor["path"]), descriptor)
    for path, size, sha in ((N2 / "analyze_targeted_results_v01.py", 66275, "4274d682da303954689bbb318750a91a49b407961f26d718104e1890a0ae4d0f"),
        (T / "run_temporal_contrast_pilot.py", 42637, "0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05")):
        pin(path, dict(bytes=size, sha256=sha))
    namespace = dict(globals(), HELPER=T / "run_temporal_contrast_pilot.py",
                     HELPER_SHA="0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05")
    detached(N2 / "analyze_targeted_results_v01.py", {"tokenize", "strict_rule", "scorers"}, namespace)
    greedy, JOINT, scorer = namespace["scorers"](registration["source_owner_pins"])
    captures = {}
    cell = freeze["cells"][0]
    root = Path(cell["summary"]["path"]).parent
    for state in ("baseline", "trained"):
        for name in PANELS:
            raw_path = root / (state + "-" + name + "-raw.json")
            joint_path = root / (state + "-" + name + "-joint.json")
            raw = read(raw_path, cell["results"][str(raw_path)])
            selected = read(joint_path, cell["results"][str(joint_path)])
            require(raw["target_access"] is False and raw["teacher_forcing"] is False and raw["model_weights_unchanged"] is True,
                    "Target-free saved capture required")
            sources = data["diagnostic_populations"][name]
            require(len(raw["occurrences"]) == len(raw["inference"]["rows"]) == len(selected["rows"]) == COUNTS[name], "Full input coverage required")
            for source, occurrence, raw_row, chosen in zip(sources, raw["occurrences"], raw["inference"]["rows"], selected["rows"], strict=True):
                require(source["id"] == occurrence["id"] == chosen["id"] and occurrence["source_sha256"] == raw_row["source_sha256"]
                        == hashlib.sha256(source["source_text"].encode()).hexdigest(), "Capture source join failed")
                JOINT["_validated"](source["source_text"], occurrence["scores"])
                greedy["_verify_greedy"](source["source_text"], occurrence["scores"], raw_row)
                replay = JOINT["select_joint_spans"](source["source_text"], occurrence["scores"], top_k=8, max_search_nodes=50000)
                require(replay == chosen["result"], "Original joint replay differs")
                require(replay["independent_greedy"]["canonical_ir"] == raw_row["canonical_ir"] and
                        replay["independent_greedy"]["status"] == raw_row["status"], "Original greedy replay differs")
            captures[state, name] = raw, selected["rows"]
    # All fixed routes and baseline replays are defined before opening evaluation references.
    composed = {}
    provenance = []
    for variant, fields in plan["variants"].items():
        for name in PANELS:
            parent, _ = captures["baseline", name]
            trained, _ = captures["trained", name]
            occurrences, raw_rows, chosen_rows = [], [], []
            for source, left, right in zip(data["diagnostic_populations"][name], parent["occurrences"], trained["occurrences"], strict=True):
                require(floats(left["scores"]["modality_logits"]) == floats(right["scores"]["modality_logits"]), "Parent modality parity differs")
                occurrence = deepcopy(left) if fields is None else compose(source, left, right, fields)
                chosen = JOINT["select_joint_spans"](source["source_text"], occurrence["scores"], top_k=8, max_search_nodes=50000)
                raw_row = deepcopy(chosen["independent_greedy"])
                raw_row["source_sha256"] = occurrence["source_sha256"]
                occurrences.append(occurrence)
                raw_rows.append(raw_row)
                chosen_rows.append(dict(id=source["id"], result=chosen))
                provenance.append(dict(variant=variant, panel=name, id=source["id"], source_sha256=occurrence["source_sha256"],
                    parent_scores_sha256=digest(left["scores"]), trained_scores_sha256=digest(right["scores"]),
                    composed_scores_sha256=digest(occurrence["scores"]),
                    temporal_logits=occurrence["scores"]["presence_logits"]["temporal"],
                    greedy_status=raw_row["status"], greedy_reason=raw_row["reason"], greedy_ir=raw_row["canonical_ir"],
                    joint_status=chosen["status"], joint_reason=chosen["reason"], joint_ir=chosen["canonical_ir"],
                    joint_result_sha256=digest(chosen), greedy_result_sha256=digest(raw_row),
                    actual_owner_report=False, trained_model=False))
            composed[variant, name] = dict(occurrences=occurrences, inference=dict(rows=raw_rows)), chosen_rows
    source_only_decisions_sha256 = digest(provenance)
    packet = read(Path(freeze["reference_packet"]["path"]), freeze["reference_packet"])
    require(packet["geometry_review_packet"]["semantic_gold"] is False and packet["split_contract"]["shared_authored_templates"] is True,
            "Previously exposed authored scope differs")
    populations = deepcopy(data["diagnostic_populations"])
    metadata = deepcopy(data["diagnostic_metadata"])
    populations["authored_eval"] = [r["model_example"] for r in packet["geometry_review_packet"]["authored_eval"]]
    metadata["authored_eval"] = [{k: r[k] for k in ("id", "class_name", "group_id", "pair_id", "pair_variant")}
                                for r in packet["geometry_review_packet"]["authored_eval"]]
    require([{k: r[k] for k in ("id", "source_text", "latent")} for r in populations["authored_eval"]]
            == data["diagnostic_populations"]["authored_eval"], "Reference/source join differs")
    results, scores = [], {}
    for variant in plan["variants"]:
        for name in PANELS:
            raw, selected = composed[variant, name]
            if name == "law":
                require(all("canonical_ir" not in r for r in populations[name]), "Law references prohibited")
                results.append(dict(variant=variant, panel=name, row_count=COUNTS[name], reference_scored=False,
                    raw_exact_ir=None, joint_exact_ir=None, raw_abstentions=sum(r["status"] != "decoded" for r in raw["inference"]["rows"]),
                    joint_abstentions=sum(r["result"]["status"] != "selected" for r in selected)))
                continue
            score = scorer["score_panel"](populations[name], metadata[name], raw, selected)
            scores[variant, name] = score
            permissions = permission_summary(populations[name], raw, selected)
            results.append(dict(variant=variant, panel=name, reference_scored=True, **compact_score(score),
                joint_abstentions=sum(r["result"]["status"] != "selected" for r in selected), permission_outcomes=permissions))
            if variant in ("parent", "split_features"):
                prior_state = "split-baseline" if variant == "parent" else "split-features"
                old = next(r for r in prior["state_and_panel_results"] if r["state"] == prior_state and r["panel"] == name)
                for new_key, old_key in (("raw_exact_ir", "raw_exact_IR"), ("joint_exact_ir", "joint_exact_IR"),
                        ("role_exact_counts", "role_exact_counts"), ("joint_role_exact_counts", "joint_role_exact_counts"),
                        ("temporal_false_positives", "temporal_false_positives"), ("temporal_false_negatives", "temporal_false_negatives")):
                    require(score[new_key] == old[old_key], "Retained baseline metrics differ")
    matched = [dict(variant=variant, reference_variant=reference, panel=name,
                   **differences(scores[reference, name]["rows"], scores[variant, name]["rows"]))
               for variant in ("parent_temporal_presence", "parent_all_optional_presence")
               for reference in ("parent", "split_features") for name in PANELS[:-1]]
    gates = {}
    for variant in plan["variants"]:
        old = next(r for r in results if r["variant"] == variant and r["panel"] == "old_tune")
        gates[variant] = dict(raw_exact_ir=old["raw_exact_ir"], joint_exact_ir=old["joint_exact_ir"],
            permission_outcomes=old["permission_outcomes"],
            met=old["raw_exact_ir"] == old["joint_exact_ir"] == 96 and all(
                counts["P_to_O"] == counts["P_to_F"] == counts["P_abstentions"] == 0
                for counts in old["permission_outcomes"].values()))
    require(digest(provenance) == source_only_decisions_sha256, "Post-reference decision drift")
    own = pin(Path(__file__).resolve())
    for path, expected in list(OBSERVED.items()):
        pin(Path(path), expected)
    report = dict(schema="legal-temporal-presence-saved-score-analysis/v1", passed=True, findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(), plan=pin(PLAN), analyzer=own,
        variants=plan["variants"], panel_results=results, matched_changes=matched, legacy_gate=gates,
        row_scores={variant: {name: scores[variant, name]["rows"] for name in PANELS[:-1]} for variant in plan["variants"]},
        source_only_decision_provenance=provenance, decisions_frozen_before_evaluation_packet_open_sha256=source_only_decisions_sha256,
        input_pins=OBSERVED, actual_model_forwards=0, optimizer_updates=0, checkpoint_JSON_parses=0,
        numerical_imports=0, remote_requests=0, resource_API_calls=0, new_checkpoint=None, trained_model=False,
        source_occurrences_per_variant=392, exposed_authored_targets_per_variant=384, unreviewed_law_rows_per_variant=8,
        baseline_greedy_and_joint_replayed=True, learned_span_boundaries_preserved=True, all392_modality_vectors_bit_identical=True,
        evaluation_references_used_for_routing=False, semantic_accuracy=None, independent_statutory_gold=False,
        genuine_latent_semantics_qualified=False, broader_logic_families_qualified=False, Lake_executed=False, default_promotion=False,
        limitations=["Previously exposed authored shared-template diagnostics, not independent US Code accuracy.",
            "Presence routing is saved-score composition, not a trained decoder or qualified model inference implementation.",
            "Passing legacy retention is necessary but does not establish legal fidelity or justify default promotion."])
    raw = json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    require(len(raw) < plan["storage_budget_bytes"], "Declared storage budget exceeded")
    WRITING = True
    with OUTPUT.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(output=str(OUTPUT), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
        panels=[{k: r[k] for k in ("variant", "panel", "raw_exact_ir", "joint_exact_ir")} for r in results], legacy_gate=gates), sort_keys=True))


if __name__ == "__main__":
    main()
