"""Frozen retained raw384/source-only span comparison; zero new encoder or fit.

Use only after a current independent protocol review under the unchanged
historical guardian. Rebuild the source cache from the prior native receipt so
its absolute producer paths bind this isolated checkout. Every raw proposal or
abstention is preserved. The eight exposed law occurrences are development
diagnostics, without semantic targets or legal/proof admission.

Capture the unchanged original decoder forward pass. Joint span selections are
separate readout proposals; original outputs/refusals and all presence/modality
decisions are preserved. No additional encoder, training or target access.
"""
from contextlib import ExitStack
from hashlib import sha256
import argparse
import ctypes.util
import importlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import time
from types import ModuleType
from unittest.mock import patch

STATE = {"created_output": None, "stage": "preparation", "raw_reports_written": []}
CONTROLS = ("none", "zero", "disabled", "rotate")
IMPORT_FIX_FILES = {
    "library_pin": "/usr/lib/aarch64-linux-gnu/libdl.so.2",
    "ctypes_util_pin": "/usr/lib/python3.12/ctypes/util.py",
    "cuda_pathfinder_pin": "/home/barberb/.local/lib/python3.12/site-packages/cuda/pathfinder/_dynamic_libs/load_dl_linux.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    value = json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode("utf-8")


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file()
        and not path.is_symlink(), "canonical ordinary pinned file required")
    digest, count = sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block); count += len(block)
    return dict(path=str(path), bytes=count, sha256=digest.hexdigest())


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return pin(path)


def bootstrap(root):
    sys.path.insert(0, str(root))
    for name in ("ipfs_datasets_py", "ipfs_datasets_py.logic", "ipfs_datasets_py.logic.legal_ir",
        "ipfs_datasets_py.logic.formalization", "ipfs_datasets_py.logic.formalization.autoencoder",
        "ipfs_datasets_py.utils", "ipfs_datasets_py.optimizers",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer"):
        module = ModuleType(name)
        module.__path__ = [str(root.joinpath(*name.split(".")))]
        module.__file__ = str(root.joinpath(*name.split("."), "__init__.py"))
        sys.modules[name] = module


def denial(operation):
    # Distinct function identities avoid conflicting Torch Dynamo rule entries.
    def refuse(*args, **kwargs):
        raise AssertionError(operation + " prohibited in frozen span comparison")
    return refuse


def model_observation(model, torch):
    if model is None:
        return dict(model_loaded=False, tensor_sha256=None, modes=None, flags=None, gradients=None)
    digest = sha256()
    for name, tensor in sorted(model.state_dict().items()):
        require(tensor.device.type == "cpu", "CPU-only retained model required")
        header = canonical(dict(name=name, dtype=str(tensor.dtype), shape=list(tensor.shape)))
        raw = bytes(tensor.detach().contiguous().reshape(-1).view(torch.uint8).tolist())
        digest.update(struct.pack("<Q", len(header))); digest.update(header)
        digest.update(struct.pack("<Q", len(raw))); digest.update(raw)
    return dict(model_loaded=True, tensor_sha256=digest.hexdigest(),
        modes=[[name, module.training] for name, module in model.named_modules()],
        flags=[[name, parameter.requires_grad] for name, parameter in model.named_parameters()],
        gradients=[[name, parameter.grad is None] for name, parameter in model.named_parameters()])


def main(args):
    started = time.monotonic()
    plan = read(args.plan)
    require(plan["schema"] == "retained-span-joint-readout-plan/v1"
        and plan["dimension"] == 384 and plan["source_count"] == 8
        and plan["controls"] == list(CONTROLS) and plan["actual_optimizer_updates"] == 0
        and plan["encoder_execution_planned"] is False and plan["semantic_gold"] is False
        and len(plan["decoder_states"]) == 2, "exact frozen two-lane/eight-source plan required")
    originals = plan["artifacts"]
    require(plan["runner_path"] == str(Path(__file__).resolve()), "exact joint comparison runner path required")
    import_fix = plan["ctypes_dl_resolution"]
    require(type(import_fix) is dict and set(import_fix) == {
        "schema", "requested_library", "library_pin", "ctypes_util_pin", "cuda_pathfinder_pin",
        "subprocess_fallback_allowed", "unlisted_library_names_allowed"}
        and import_fix["schema"] == "pinned-libdl-resolution/v1"
        and import_fix["requested_library"] == "dl"
        and import_fix["subprocess_fallback_allowed"] is False
        and import_fix["unlisted_library_names_allowed"] is False,
        "closed single-library no-subprocess import resolution required")
    for field, path in IMPORT_FIX_FILES.items():
        expected = import_fix[field]
        require(type(expected) is dict and set(expected) == {"path", "bytes", "sha256"}
            and expected["path"] == path and pin(path) == expected
            and originals.get(path) == {key: expected[key] for key in ("bytes", "sha256")},
            "exact ordinary import-fix file must enter artifact fences")
    require(ctypes.util.__file__ == IMPORT_FIX_FILES["ctypes_util_pin"],
        "stdlib ctypes.util origin differs from reviewed pin")
    for path, expected in originals.items():
        actual = pin(path)
        require({k: actual[k] for k in ("bytes", "sha256")} == expected,
            "reviewed artifact differs before execution")
    output = Path(args.output)
    require(output.is_absolute() and output.resolve() == output and not output.exists(),
        "fresh canonical comparison output required")
    output.mkdir(mode=0o700)
    STATE["created_output"] = str(output)
    forbidden = set(plan["forbidden_reference_paths"])

    def audit(event, values):
        network = {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg",
            "socket.bind", "socket.listen", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"}
        if event in network or event.startswith(("subprocess.", "os.exec", "os.spawn")) or event == "os.system":
            raise AssertionError("network/process execution prohibited in frozen span child")
        if event == "open" and isinstance(values[0], (str, bytes)):
            path = str(Path(os.fsdecode(values[0])).absolute())
            require(path not in forbidden, "target/census/reference access prohibited")

    sys.addaudithook(audit)
    bootstrap(Path(plan["package_root"]))
    spec = importlib.util.spec_from_file_location("arbitrary_native_source_preparation", plan["helper_path"])
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    lanes = []
    dl_queries = []
    with ExitStack() as stack:
        def resolve_dl(name):
            require(type(name) is str and name == "dl", "unlisted dynamic library query refused")
            require(pin(import_fix["library_pin"]["path"]) == import_fix["library_pin"],
                "pinned libdl bytes changed during import resolution")
            dl_queries.append(name)
            return import_fix["library_pin"]["path"]
        # Keep this restriction throughout the child, including lazy Torch
        # imports. Do not invoke the original finder, ldconfig or a compiler.
        stack.enter_context(patch.object(ctypes.util, "find_library", resolve_dl))
        import torch
        torch.set_num_threads(1); torch.set_num_interop_threads(1)
        # Existing restore constructs temporary Adam objects to check custody;
        # it does not step them. Permit construction and forbid every update.
        for owner, name in ((torch.optim.Optimizer, "step"), (torch.optim.Adam, "step"),
            (torch.optim.AdamW, "step"), (torch.Tensor, "backward"),
            (torch.autograd, "backward"), (torch.autograd, "grad")):
            stack.enter_context(patch.object(owner, name, denial(str(owner) + "." + name)))
        producer = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime")
        stack.enter_context(patch.object(producer, "produce_native_embedding_receipt", denial("native encoder")))
        generation = output / "source-cache-generation"
        production = helper.prepare(plan["source_configuration"], output_directory=generation)
        cache_path = generation / "source-cache.json"
        cache = read(cache_path)
        ids = [row["id"] for row in cache["rows"]]
        require(cache["status"] == "ready" and cache["complete"] is True and ids == plan["row_ids"]
            and production["native384_producer_calls_started"] == 0
            and production["native384_producer_calls_returned"] == 0,
            "receipt reuse must provide all original occurrences without encoding")
        runtime = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.arbitrary_native_span_runtime")
        require(runtime.source_owner_paths() == {name: value["path"] for name, value in plan["source_owner_pins"].items()},
            "fixed current span owner inventory differs")
        capture_module = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture")
        joint_module = importlib.import_module("ipfs_datasets_py.logic.legal_ir.joint_span_selection")
        for name, expected in plan["additional_readout_owner_pins"].items():
            module = sys.modules[name]
            require(Path(module.__file__).resolve() == Path(expected["path"])
                and pin(expected["path"]) == expected, "additional readout owner differs")
        require(plan["joint_selection"]["top_k"] == 8
            and plan["joint_selection"]["max_search_nodes"] == 50000
            and plan["joint_selection"]["immutable_presence_and_modality"] is True
            and plan["joint_selection"]["original_greedy_outputs_preserved"] is True,
            "exact bounded joint readout contract required")
        requests = read(plan["source_configuration"]["source_requests_pin"]["path"])
        require([row["id"] for row in requests] == ids, "source score joins differ")
        source_rows = [{"id": row["id"], "source_text": row["source_text"]} for row in requests]
        options = []
        prepared = []
        for state in plan["decoder_states"]:
            selected = dict(checkpoint_pin=state["checkpoint_pin"], source_cache_pin=pin(cache_path),
                source_requests_pin=plan["source_configuration"]["source_requests_pin"],
                native384_receipt_refs=plan["source_configuration"]["native384_receipt_refs"],
                source_artifact_pins=plan["source_configuration"]["source_artifact_pins"],
                source_owner_pins=plan["source_owner_pins"], row_ids=ids,
                raw384_equivalence_pin=plan["raw384_equivalence_pin"])
            options.append((state, selected))
            for control in CONTROLS:
                candidate_plan = runtime.prepare_arbitrary_native_span_runtime(**selected, control=control)
                prepared.append(dict(name=state["name"], control=control, plan=candidate_plan))
        write(output / "all-control-plans-before-opening.json", prepared)
        for state, selected in options:
            ambient = torch.get_rng_state().clone()
            with torch.random.fork_rng(devices=[]):
                handle = runtime.open_arbitrary_native_span_decoder(**selected, control="none")
                before = model_observation(handle.model, torch)
                if before["model_loaded"]:
                    require(all(value for _, value in before["gradients"]), "restored model has preexisting gradients")
                for control in CONTROLS:
                    rng = torch.get_rng_state().clone()
                    current_plan = next(item["plan"] for item in prepared
                        if item["name"] == state["name"] and item["control"] == control)
                    capture = capture_module.RetainedSpanScoreCapture(source_rows,
                        submitted_positions=current_plan["submitted_positions"])
                    STATE.update(stage="original_inference", name=state["name"], control=control)
                    with capture.attach(handle.model):
                        report = handle.infer_cached(control=control)
                    report_pin = write(output / (state["name"] + "-" + control + ".json"), report)
                    STATE["raw_reports_written"].append(report_pin)
                    STATE["stage"] = "diagnostic_finalization"
                    sidecar = capture.finalize(report)
                    # Selector packet/sidecar shape verified after API freeze.
                    joint_rows = []
                    for occurrence, row in zip(source_rows, sidecar["rows"], strict=True):
                        require(occurrence["id"] == row["id"], "captured occurrence order differs")
                        result = None if row["scores"] is None else joint_module.select_joint_spans(
                            occurrence["source_text"], row["scores"],
                            top_k=8, max_search_nodes=50000)
                        joint_rows.append(dict(id=row["id"], result=result))
                    sidecar_pin = write(output / (state["name"] + "-" + control + "-scores.json"), sidecar)
                    joint_pin = write(output / (state["name"] + "-" + control + "-joint.json"),
                        dict(schema="retained-span-joint-readout-lane/v1", rows=joint_rows,
                             new_optimizer_updates=0, semantic_accuracy=None, qualified=False,
                             proof_authority=False, default_promotion=False))
                    after = model_observation(handle.model, torch)
                    require(before == after and torch.equal(rng, torch.get_rng_state()),
                        "inference changed tensors/modes/flags/gradients or CPU RNG")
                    require(type(report["rows"]) is list and [row["id"] for row in report["rows"]] == ids,
                        "raw output must retain all ordered requested occurrences")
                    lanes.append(dict(name=state["name"], control=control, checkpoint=state["checkpoint_pin"],
                        report=report_pin, score_sidecar=sidecar_pin, joint_readout=joint_pin, requested_source_count=len(ids),
                        model_custody_before=before, model_custody_after=after,
                        model_custody_observed=before["model_loaded"],
                        model_tensors_modes_flags_gradients_unchanged=True if before["model_loaded"] else None,
                        inference_cpu_rng_unchanged=True))
                del handle
            require(torch.equal(ambient, torch.get_rng_state()), "opening changed ambient CPU RNG")
    for path, expected in originals.items():
        actual = pin(path)
        require({k: actual[k] for k in ("bytes", "sha256")} == expected,
            "original artifact changed during frozen comparison")
    summary = dict(schema="retained-span-joint-readout-results/v1", status="completed",
        dimension=384, source_count=8, control_count=4, decoder_lane_count=2,
        requested_output_count=64, lanes=lanes, source_cache=pin(cache_path), source_cache_preparation=production,
        raw384_equivalence_pin=plan["raw384_equivalence_pin"], actual_optimizer_updates=0,
        ctypes_dl_resolution=dict(profile=import_fix, admitted_query_count=len(dl_queries),
            admitted_queries=dl_queries, subprocess_fallback_executed=False,
            unlisted_library_names_allowed=False, pinned_library_initial_and_closing_hashed=True),
        actual_encoder_calls=0, checkpoint_selection_executed=False, all_original_artifacts_byte_exact=True,
        full_checkpoint_and_saved_optimizer_bytes_unchanged=True,
        temporary_restoration_optimizer_constructed=any(row["model_custody_observed"] for row in lanes),
        live_optimizer_moments_retained_by_decoder=False,
        model_lane_load_count=sum(row["control"] == "none" and row["model_custody_observed"] for row in lanes),
        original_targets_accessed=False, semantic_gold=False, source_semantics_verified=False,
        historical_corpus_not_opened_by_child=True,
        legal_fidelity_qualified=False, proof_authority=False, Lake_executed=False, default_promotion=False,
        qualified=False, training_executed=False, encoder_executed=False, development_cohort_previously_exposed=True,
        independent_semantic_holdout=False, multi_rule_supported=False,
        full_third_party_import_graph_qualified=False,
        selected_canonical_dependency_files_initial_and_closing_hashed=True,
        output_scope="original greedy dispositions plus separate same-pass scores and limited-pool joint candidates",
        joint_selection=plan["joint_selection"],
        score_capture_additional_forward_calls=0, joint_readout_is_original_greedy_output=False,
        semantic_accuracy=None, semantic_gain_established=False,
        elapsed_seconds=time.monotonic() - started,
        resource_scope="unchanged historical guardian:2CPU/1536MiB/1child/200MB/300seconds")
    write(output / "summary.json", summary)
    print(json.dumps(dict(status="completed", requested_output_count=64, actual_optimizer_updates=0,
        actual_encoder_calls=0)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        main(args)
    except Exception as error:
        if STATE["created_output"] is not None:
            write(Path(STATE["created_output"]) / "diagnostic-failure.json", dict(
                schema="retained-joint-readout-child-failure/v1", **STATE,
                error_type=type(error).__name__, detail=str(error),
                optimizer_updates=0, original_raw_outputs_precede_diagnostics=True,
                semantic_accuracy=None, qualified=False, proof_authority=False))
        raise
