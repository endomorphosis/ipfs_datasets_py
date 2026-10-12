"""Prepare a bounded authored data ablation; no model construction or fitting."""
from collections import Counter
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path

F = Path(__file__).resolve().parent
D = F / "datasets"
H = F.parent / "legal-structured-training-20261011-01"
J = F.parent / "legal-joint-readout-20261011-01"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, "duplicate JSON key"
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def pin(path):
    path = Path(path)
    assert path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=sha256(raw).hexdigest())


def write(name, value):
    path = F / name
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return pin(path)


def old_metadata(row):
    return dict(id=row["id"], class_name="legacy_authored", group_id=None,
                pair_id=None, pair_variant=None)


def main():
    import bootstrap_inert
    bootstrap_inert.install()
    corpus = importlib.import_module("ipfs_datasets_py.logic.legal_ir.temporal_role_contrast_corpus")
    span = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula")
    # audit_examples tokenizes and checks supplied labels; it constructs no Torch model.
    fresh = corpus.build_corpus()
    fresh_pin = write("authored-temporal-contrast-corpus-v01.json", fresh)
    prior_plan = read(H / "experiment-plan.json")
    old_export_path = H / "authored-train-tune-only.json"
    old_export_pin = pin(old_export_path)
    assert old_export_pin == prior_plan["train_tune_export"]
    old = read(old_export_path)
    seen = Counter()
    rehearsal = []
    for row in old["populations"]["train"]:
        rule = row["canonical_ir"]["rules"][0]
        key = (rule["modality"], bool(rule["conditions"]), bool(rule["exceptions"]), bool(rule["temporal"]))
        if seen[key] < 4:
            rehearsal.append(row)
            seen[key] += 1
    assert len(rehearsal) == 96 and len(seen) == 24 and set(seen.values()) == {4}
    assert len(old["populations"]["tuning"]) == 96
    examples, meta = {}, {}
    for split, count in (("train", 72), ("tuning", 36), ("challenge", 36)):
        rows = fresh["populations"][split]
        assert len(rows) == count
        examples[split] = [row["model_example"] for row in rows]
        meta[split] = [{key: row[key] for key in ("id", "class_name", "group_id", "pair_id", "pair_variant")} for row in rows]
        assert span.audit_examples(examples[split])["all_supported"]
    plain = [row for row in fresh["populations"]["train"] if row["class_name"] == "plain_deadline"]
    assert len(plain) == 12
    populations = dict(control_train=rehearsal + [row["model_example"] for row in plain],
                       contrast_train=rehearsal + examples["train"],
                       old_tune=old["populations"]["tuning"], fresh_tune=examples["tuning"],
                       fresh_challenge=examples["challenge"])
    metadata = dict(control_train=[old_metadata(row) for row in rehearsal] +
                    [{key: row[key] for key in ("id", "class_name", "group_id", "pair_id", "pair_variant")} for row in plain],
                    contrast_train=[old_metadata(row) for row in rehearsal] + meta["train"],
                    old_tune=[old_metadata(row) for row in populations["old_tune"]],
                    fresh_tune=meta["tuning"], fresh_challenge=meta["challenge"])
    law_pin = pin(H / "exposed-law-source-only.json")
    assert law_pin == prior_plan["law_diagnostic_export"]
    law_export = read(law_pin["path"])
    populations["law"] = law_export["rows"]
    assert len(populations["law"]) == 8
    for key in ("requests", "native_receipt"):
        assert pin(law_export[key]["path"]) == law_export[key]
    requests = read(law_export["requests"]["path"])
    assert len(requests) == 8
    for artifact in law_export["source_context_pins"].values():
        assert pin(artifact["path"]) == artifact
    for request, row in zip(requests, populations["law"], strict=True):
        assert request["id"] == row["id"] and request["source_text"] == row["source_text"]
        source = request["source"]
        artifact = law_export["source_context_pins"][source["artifact"]["sha256"]]
        assert Path(artifact["path"]).read_bytes()[source["byte_start"]:source["byte_end"]].decode() == row["source_text"]
    data_pin = write("training-export-v01.json", dict(schema="temporal-contrast-training-export/v1",
        populations=populations, metadata=metadata, semantic_gold=False,
        provenance="authored_engineering_and_unreviewed_law_diagnostics_separate"))
    ambiguity = fresh["populations"]["ambiguous_diagnostics"]
    audit = write("inert-ambiguity-audit-v01.json", dict(schema="temporal-contrast-ambiguity-audit/v1",
        rows=ambiguity, legacy_label_audit=span.audit_examples([row["refusal_candidate"] for row in ambiguity]),
        excluded_from_supervised_populations=True, semantic_gold=False))
    assert not read(audit["path"])["legacy_label_audit"]["accepted_ids"]
    owners = {}
    for name, previous in prior_plan["source_owner_pins"].items():
        target = D / Path(previous["path"]).relative_to(H / "datasets")
        owners[name] = pin(target)
        assert {k: owners[name][k] for k in ("bytes", "sha256")} == {k: previous[k] for k in ("bytes", "sha256")}
    for name in ("joint_span_selection", "temporal_role_contrast_corpus"):
        owners["ipfs_datasets_py.logic.legal_ir." + name] = pin(D / "ipfs_datasets_py/logic/legal_ir" / (name + ".py"))
    owners["ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture"] = pin(
        D / "ipfs_datasets_py/logic/formalization/autoencoder/retained_span_score_capture.py")
    parent = pin(F.parent / "legal-decoder-native-conditioning-20261002/run-01/source_only-1729/checkpoint-400.json")
    assert parent["sha256"] == "5df537d8c7141578c1355af43317b9c5a327305295a11760aee2897244bc5dbb"
    paths = [Path(__file__), F / "bootstrap_inert.py", F / "run_temporal_contrast_pilot.py", F / "run_scope_guardian.py",
             Path(data_pin["path"]), Path(fresh_pin["path"]), Path(audit["path"]), Path(parent["path"]),
             old_export_path, Path(law_pin["path"]), H / "experiment-plan.json", J / "raw384-equivalence.json",
             F / "resource-compatibility-v01.json", F / "temporal-recovery-review-v01.json"]
    paths += [Path(value["path"]) for value in owners.values()]
    paths += [Path(law_export[key]["path"]) for key in ("requests", "native_receipt")]
    paths += [Path(value["path"]) for value in law_export["source_context_pins"].values()]
    for path, expected in prior_plan["artifacts"].items():
        if "/site-packages/" in path or path.startswith("/usr/lib/"):
            assert {k: pin(path)[k] for k in ("bytes", "sha256")} == expected
            paths.append(Path(path))
    artifacts = {str(path): {k: pin(path)[k] for k in ("bytes", "sha256")} for path in paths}
    arms = [dict(name=name, training_population=population, training_manifest_sha256=digest(populations[population]),
                 training_count=len(populations[population]), new_steps=32)
            for name, population in (("control", "control_train"), ("contrast", "contrast_train"))]
    plan = dict(schema="temporal-contrast-source-only-two-arm-plan/v1", package_root=str(D),
        runner_path=str(F / "run_temporal_contrast_pilot.py"), guardian_path=str(F / "run_scope_guardian.py"),
        source_owner_pins=owners, artifacts=artifacts, ctypes_dl_resolution=prior_plan["ctypes_dl_resolution"],
        historical_parent_file_pin=parent,
        # Previously verified canonical digest.  The retained save format makes
        # it equal to this particular file SHA; the admitted child checks both.
        historical_parent_canonical_sha256="5df537d8c7141578c1355af43317b9c5a327305295a11760aee2897244bc5dbb",
        parent_base_canonical_sha256="fd7eb4bd7c8c5d5abb23d168e6b67300497eea6243b5c8cd5779cfbc566d5279",
        parent_model_state_sha256="54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb",
        data_export=data_pin, inert_audit_pin=audit, arms=arms,
        tuning_population="old_tune", tuning_manifest_sha256=digest(populations["old_tune"]),
        diagnostic_panels=[dict(name=name, population=name, count=len(populations[name]),
            has_authored_reference=name != "law",
            provenance="previously_exposed_unreviewed_law_source_only" if name == "law" else
                       "authored_synthetic_not_legal_authority")
            for name in ("old_tune", "fresh_tune", "fresh_challenge", "law")],
        context_contract=dict(dimension=384,
            representation_id="source_only_dormant384_retained_and_zero_authored_contrast/v1",
            producer_sha256=pin(Path(__file__))["sha256"],
            training_index_sha256=digest({arm["name"]: arm["training_manifest_sha256"] for arm in arms})),
        resource_contract=prior_plan["resource_contract"], forbidden_reference_paths=prior_plan["forbidden_reference_paths"],
        training_seconds_per_arm=32, seed=1729, dimension=384, latent_enabled=False,
        semantic_gold=False,
        independent_semantic_holdout=False, checkpoint_selection_executed=False, default_promotion=False,
        encoder_execution_planned=False, Lake_executed=False)
    print(json.dumps(write("experiment-plan-v01.json", plan), sort_keys=True))


if __name__ == "__main__":
    main()
