"""Reproduce cached generation, then evaluate in a separate invocation.

Original artifacts stay at their existing paths. No targets are opened in the
generation phase; the original raw donor is read only for its codec/config/state.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.abc
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

PACKAGE = "ipfs_datasets_py.logic.formalization.autoencoder."
HERE = Path(__file__).resolve().parent
FORBIDDEN_ARTIFACT_PATHS = set()
HISTORICAL_CANDIDATES = {
    384: (1802992, "94bc4aba998afb490e903da76579dc63f9324737c4a1fcf0e9396c0014e805bb"),
    768: (2325658, "66ccfa52204a19d50694d556afb868e4a3482ddabc5f54988f30befe9c5be355"),
}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def pin(path):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                              allow_nan=False) + "\n")
    return pin(path)


def fail(*args, **kwargs):
    raise AssertionError("training/optimizer/fitting path must not execute")


class ForbiddenImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"duckdb", "ducklake", "sentence_transformers", "transformers"}:
            raise AssertionError("encoder/database import must not execute: " + fullname)
        if "modal_latent_formula" in fullname or (fullname.startswith(PACKAGE) and "training" in fullname):
            raise AssertionError("historical training owner must not import: " + fullname)


def audit_generation(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("network operation must not execute")
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = str(args[0])
        if name in FORBIDDEN_ARTIFACT_PATHS or "training-rows.json" in name or Path(name).name in {
                "384-source-only-candidates.json", "768-source-only-candidates.json"}:
            raise AssertionError("reference/previous candidate opened during generation: " + name)


def source_pins(repo):
    folder = repo / "ipfs_datasets_py/logic/formalization/autoencoder"
    names = (*importlib.import_module(PACKAGE + "contextual_legal_ir_runtime").SOURCE_OWNER_NAMES,
             "contextual_legal_ir_output", "decoder_source_fidelity")
    result = {name: pin(folder / (name + ".py")) for name in names}
    legal = repo / "ipfs_datasets_py/logic/legal_ir"
    for name in ("canonical_contracts", "canonical_decompiler"):
        result[name] = pin(legal / (name + ".py"))
    for path in sorted((repo / "tests/unit/logic/formalization/autoencoder").glob("test_contextual_legal_ir_*.py")):
        result[path.name] = pin(path)
    return result


def git_head(repo):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def inputs(runtime, survey, lane, repo):
    folder = repo / "ipfs_datasets_py/logic/formalization/autoencoder"
    cached = lane["cached_file_pins"]
    rows = json.loads(Path(cached["source_only_inputs"]["path"]).read_text())
    return dict(request=dict(ir_family_id="legal_ir", dimension=lane["dimension"],
        dimension_role="input_embedding", task_id="semantic_IR_reconstruction",
        checkpoint_sha256=lane["original_checkpoint_pin"]["sha256"]),
        checkpoint_pin=lane["original_checkpoint_pin"],
        preprocessing_pin=cached["original_preprocessing"],
        donor_checkpoint_pin=survey["original_raw_donor_pin"],
        source_inputs_pin=cached["source_only_inputs"], source_contexts_pin=cached["source_only_contexts"],
        source_owner_pins={name: pin(folder / (name + ".py")) for name in runtime.SOURCE_OWNER_NAMES},
        row_ids=[row["id"] for row in rows], deadline_seconds=120)


def generate(repo, survey):
    # Import/preparation is observed before Torch is imported in this process.
    required_assets = []
    for lane in survey["lanes"]:
        required_assets.extend([lane["original_checkpoint_pin"], *[lane["cached_file_pins"][key]
            for key in ("original_preprocessing", "source_only_inputs", "source_only_contexts")]])
    required_paths = {value["path"] for value in required_assets}
    FORBIDDEN_ARTIFACT_PATHS.update(value["path"] for value in survey["original_file_pins_before"]
                                    if value["path"] not in required_paths)
    FORBIDDEN_ARTIFACT_PATHS.discard(survey["original_raw_donor_pin"]["path"])
    sys.meta_path.insert(0, ForbiddenImports())
    sys.addaudithook(audit_generation)
    runtime = importlib.import_module(PACKAGE + "contextual_legal_ir_runtime")
    assert "torch" not in sys.modules
    sources_before = source_pins(repo)
    # Only the eight required lane assets are opened for custody hashing here.
    # Historical scored/reference evidence is checked in the evaluator process.
    original_before = [pin(value["path"]) for value in required_assets]
    assert original_before == required_assets
    donor_before = pin(survey["original_raw_donor_pin"]["path"])
    assert donor_before == survey["original_raw_donor_pin"]
    prepared = []
    for lane in survey["lanes"]:
        options = inputs(runtime, survey, lane, repo)
        plan = runtime.prepare_contextual_legal_ir_runtime(**options)
        assert "torch" not in sys.modules and plan["original_targets_accessed"] is False
        # Retain all identities/receipts without copying original cached vectors.
        summary = {key: value for key, value in plan.items() if key != "source_inputs"}
        save(HERE / f'{lane["dimension"]}-metadata-plan.json', summary)
        prepared.append((lane, options))
    import torch
    torch.set_num_threads(1)  # Qualification caller configuration, not runtime mutation.
    receipt = dict(schema="contextual-legal-original-assets-generation-qualification/v1",
        datasets_head=git_head(repo), script_pin=pin(__file__), observed_at_utc=datetime.now(timezone.utc).isoformat(),
        preparation_torch_free=True, source_pins_before=sources_before,
        original_files_before=original_before, donor_pin_before=donor_before,
        source_only_generation=True, original_targets_opened_during_generation=False,
        encoder_executed=False, optimizer_executed=False, fitting_executed=False,
        database_or_network_executed=False, lanes=[])
    with ExitStack() as stack:
        stack.enter_context(patch.object(torch.optim.Optimizer, "__init__", fail))
        for name in runtime.SOURCE_OWNER_NAMES:
            if name.startswith("contextual_"):
                continue
            module = importlib.import_module(PACKAGE + name)
            for method in ("fit_source_normalization", "fit_source_count_prior", "run_trial", "_evaluate",
                           "unique_training_clauses", "prepare_source_contexts", "validate_training_contexts"):
                if hasattr(module, method):
                    stack.enter_context(patch.object(module, method, fail))
        for lane, options in prepared:
            started = time.monotonic()
            rng = torch.get_rng_state().clone()
            model = runtime.open_contextual_legal_ir_autoencoder(**options)
            generated = model.infer_cached()
            assert torch.equal(rng, torch.get_rng_state())
            candidate = generated["raw_candidate_report"]
            assert candidate["row_count"] == 48 and candidate["completed"]
            assert candidate["weights_unchanged"] and candidate["ambient_rng_preserved"]
            assert candidate["source_inputs_unchanged"] and not any(generated["authority"].values())
            assert candidate["model_tensor_sha256"] == lane["selected_native_tensor_sha256"]
            candidate_pin = save(HERE / f'{lane["dimension"]}-fresh-source-only-candidates.json', generated)
            receipt["lanes"].append(dict(dimension=lane["dimension"], candidate_pin=candidate_pin,
                row_count=48, source_clause_occurrences=sum(row["source_clause_count"] for row in generated["row_receipts"]),
                eos_reached=sum(row["eos_reached"] for row in candidate["predictions"]),
                model_tensor_sha256=candidate["model_tensor_sha256"], ambient_rng_preserved=True,
                weights_unchanged=True, cached_inputs_unchanged=True, elapsed_seconds=time.monotonic()-started))
            del model
    receipt["source_pins_after"] = source_pins(repo)
    receipt["original_files_after"] = [pin(value["path"]) for value in original_before]
    receipt["donor_pin_after"] = pin(donor_before["path"])
    assert receipt["source_pins_after"] == sources_before
    assert receipt["original_files_after"] == original_before and receipt["donor_pin_after"] == donor_before
    receipt.update(completed=True, qualified=False, proof_authority=False, fresh_holdout=False,
        native_profile_qualified=False, legal_prose_reconstruction_measured=False)
    saved = save(HERE / "generation-qualification.json", receipt)
    print(json.dumps(dict(receipt=saved, lanes=receipt["lanes"])))


def evaluate(repo, survey):
    # Separate process: no model loading, only persisted raw outputs and references.
    assert "torch" not in sys.modules
    output = importlib.import_module(PACKAGE + "contextual_legal_ir_output")
    generation = json.loads((HERE / "generation-qualification.json").read_text())
    assert generation["completed"] and generation["source_pins_after"] == source_pins(repo)
    assert len(survey["lanes"]) == len(generation["lanes"]) == 2
    assert [lane["dimension"] for lane in survey["lanes"]] == [384, 768]
    assert [lane["dimension"] for lane in generation["lanes"]] == [384, 768]
    previous_folder = Path(survey["lanes"][0]["cached_file_pins"]["source_only_inputs"]["path"]).parent
    previous_manifest = previous_folder / "inference-result.json"
    previous_manifest_bytes = previous_manifest.read_bytes()
    previous_manifest_pin = dict(path=str(previous_manifest), bytes=len(previous_manifest_bytes),
        sha256=hashlib.sha256(previous_manifest_bytes).hexdigest())
    assert (previous_manifest_pin["bytes"], previous_manifest_pin["sha256"]) == (
        2376560, "72ff17e1845beb9b398ac9acec35e0c9425e597a1e071a4e157d258f255eb8eb")
    previous_manifest_lanes = {lane["dimension"]: lane for lane in json.loads(previous_manifest_bytes)["lanes"]}
    receipt = dict(schema="contextual-legal-original-assets-separate-evaluation/v1",
        script_pin=pin(__file__), generation_receipt_pin=pin(HERE / "generation-qualification.json"),
        datasets_head=git_head(repo), generated_candidates_persisted_before_reference_access=True,
        model_loaded=False, training_executed=False, embeddings_generated=False,
        source_text_passed_to_decompiler=False, reference_ir_passed_to_decompiler=False,
        previous_inference_manifest_pin=previous_manifest_pin,
        fresh_holdout=False, proof_authority=False, native_profile_qualified=False, lanes=[])
    for lane, observed in zip(survey["lanes"], generation["lanes"]):
        dimension = lane["dimension"]
        assert pin(observed["candidate_pin"]["path"]) == observed["candidate_pin"]
        generated = json.loads(Path(observed["candidate_pin"]["path"]).read_text())
        predictions = generated["raw_candidate_report"]["predictions"]
        # Resolve original location independently of the qualification output folder.
        old = Path(lane["cached_file_pins"]["source_only_inputs"]["path"]).parent / f"{dimension}-source-only-candidates.json"
        old_bytes = old.read_bytes()
        previous_pin = dict(path=str(old), bytes=len(old_bytes), sha256=hashlib.sha256(old_bytes).hexdigest())
        assert (previous_pin["bytes"], previous_pin["sha256"]) == HISTORICAL_CANDIDATES[dimension]
        assert previous_manifest_lanes[dimension]["candidate_report"] == previous_pin
        previous = json.loads(old_bytes)["predictions"]
        parity = predictions == previous
        assert parity
        refs_pin = lane["cached_file_pins"]["original_training_rows"]
        assert pin(refs_pin["path"]) == refs_pin
        complete = json.loads(Path(refs_pin["path"]).read_text())["validation"]
        checkpoint = json.loads(Path(lane["original_checkpoint_pin"]["path"]).read_text())
        codec = checkpoint["codec"]
        vocabulary = codec["target_vocabulary"]
        refs = []
        for row in complete:
            target = json.loads("".join(vocabulary[token] for token in row["target_ids"][1:-1]))
            refs.append(dict(id=row["id"], target=target, clause_count=len(target["rules"])))
        agreement = output.score_contextual_legal_predictions(refs, predictions, codec=codec)
        rendered = output.render_contextual_legal_text_candidates(predictions, codec=codec)
        texts = [dict(id=row["id"], source_text=row["source_text"]) for row in complete]
        text_score = output.score_legal_text_reconstructions(texts, rendered["reconstructions"])
        metrics = agreement["reference_agreement"]["metrics"]
        assert metrics["ordered_exact"] == agreement["canonical_contract_exact"] == 48
        assert metrics["expected_rules"] == 180
        qualifiers_empty = all(not rule[field] for ref in refs for rule in ref["target"]["rules"]
                               for field in ("conditions", "exceptions", "temporal"))
        lane_receipt = dict(dimension=dimension, reference_pin=refs_pin, candidate_pin=observed["candidate_pin"],
            previous_candidate_pin=previous_pin, exact_previous_token_status_eos_parity=parity,
            ir_metrics=metrics, by_facet=agreement["reference_agreement"]["by_facet"],
            canonical_contract_exact=agreement["canonical_contract_exact"],
            reference_qualifier_fields_all_empty=qualifiers_empty,
            original_text_metrics={key: value for key, value in text_score.items() if key != "rows"},
            ir_report_pin=save(HERE / f"{dimension}-semantic-ir-evaluation.json", agreement),
            rendering_pin=save(HERE / f"{dimension}-source-withheld-text-rendering.json", rendered),
            text_report_pin=save(HERE / f"{dimension}-original-text-evaluation.json", text_score))
        receipt["lanes"].append(lane_receipt)
    assert "torch" not in sys.modules
    receipt["original44_file_pins_after_generation"] = [pin(value["path"]) for value in survey["original_file_pins_before"]]
    assert receipt["original44_file_pins_after_generation"] == survey["original_file_pins_before"]
    receipt.update(completed=True, evaluator_torch_free=True,
        corpus_scope="Authored exposed48-row regression panel per dimension; all qualifiers empty; not fresh holdout or8192-span qualification.")
    saved = save(HERE / "separate-evaluation.json", receipt)
    print(json.dumps(dict(receipt=saved, lanes=[{k: v for k, v in row.items() if k in
        {"dimension", "ir_metrics", "canonical_contract_exact", "original_text_metrics", "exact_previous_token_status_eos_parity"}}
        for row in receipt["lanes"]])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("generate", "evaluate"))
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    sys.path.insert(0, str(repo))
    survey = json.loads((HERE / "source-survey/source-survey.json").read_text())
    (generate if args.phase == "generate" else evaluate)(repo, survey)
