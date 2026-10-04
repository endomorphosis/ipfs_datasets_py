"""Portable stdlib reader controls driven by retained native receipt bytes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

import audit_modal_formula_cuda as reader


def main():
    archive, output = Path(sys.argv[1]), Path(sys.argv[2])
    if output.exists():
        raise ValueError("guard output must be new")
    started = time.monotonic()
    before = reader._snapshot(archive)
    record = reader._parse((archive / "result.json").read_bytes())
    files = {name: (archive/name).read_bytes() for name in before}
    def load(name):
        if name not in files:
            raise ValueError("artifact outside closed inventory")
        return files[name]
    reader.validate(record, load)
    controls = []
    def add(name, mutate):
        value = deepcopy(record)
        mutate(value)
        try:
            reader.validate(value, load)
        except (ValueError, KeyError, TypeError) as error:
            controls.append({"name": name, "rejected": True, "message": str(error)})
            return
        raise AssertionError(name + " was accepted")
    add("native_failed", lambda r: r.update(qualified=False))
    add("native_error", lambda r: r.update(error={"type": "CUDA OOM"}))
    add("discovery_without_kernel", lambda r: r.update(actual_initial_cuda_kernel=False))
    add("missing_cuda", lambda r: r["hardware"].update(cuda_available=False))
    add("inference_fit", lambda r: r.update(inference_training_calls=1))
    add("wrong_setup_fit_count", lambda r: r.update(setup_training_calls=0))
    add("boolean_inference_fit_count", lambda r: r.update(inference_training_calls=False))
    add("nonfinite_elapsed", lambda r: r.update(elapsed_seconds=float("nan")))
    add("boolean_elapsed", lambda r: r.update(elapsed_seconds=True))
    add("lease_not_released", lambda r: r.update(own_lease_released=False))
    add("foreign_resource_budget", lambda r: r["admission"].update(memory_mb=4096))
    add("unqualified_rss", lambda r: r.update(peak_rss_bytes=3*1024**3))
    add("unqualified_gpu_memory", lambda r: r.update(peak_gpu_allocated_bytes=3*1024**3))
    add("proof_authority", lambda r: r.update(proof_authority=True))
    add("whole_codebase_384_claim", lambda r: r.update(general_codebase_384d_qualification=True))
    add("released_weight_claim", lambda r: r.update(released_weight_qualification=True))
    add("execution_attestation_claim", lambda r: r.update(execution_attestation=True))
    add("producer_copy_alias", lambda r: r["source_pins"][0].update(copy=r["source_pins"][1]["copy"]))
    add("producer_digest", lambda r: r["source_pins"][0].update(sha256="0"*64))
    add("missing_embedding_members", lambda r: r["embeddings"].update(count=31))
    add("wrong_embedding_tokens", lambda r: r["embeddings"]["cuda"]["report"]["tokens"][0]["input_ids"].append(123))
    add("wrong_embedding_source", lambda r: r["embeddings"]["cuda"]["report"]["source_sha256"].__setitem__(0,"0"*64))
    add("wrong_embedding_device", lambda r: r["embeddings"]["cuda"]["report"]["profile"].update(device="cpu"))
    add("wrong_actual_output_device", lambda r: r["embeddings"]["cuda"]["report"]["actual_forward_batches"][0].update(output_device="cpu"))
    add("wrong_embedding_parity", lambda r: r["embeddings"].update(max_absolute_error=0.))
    add("boolean_encoder_timing", lambda r: r["embeddings"]["cuda"]["warm_boundary_seconds"].__setitem__(0,True))
    add("nonfinite_encoder_timing", lambda r: r["embeddings"]["cuda"].update(median_seconds=float("inf")))
    add("wrong_encoder_median", lambda r: r["embeddings"]["cuda"].update(median_seconds=.000001))
    add("wrong_default_gte_device", lambda r: r["existing_default_gte_path"].update(actual_model_device="cpu"))
    add("wrong_checkpoint_lineage", lambda r: r["formulas"][0]["binding"].update(dimension=384))
    add("wrong_adam_progress", lambda r: r["formulas"][0]["training_progress"].update(optimizer_steps=0))
    add("wrong_checkpoint_digest", lambda r: r["formulas"][0]["checkpoint"].update(sha256="0"*64))
    add("missing_full_batch", lambda r: r["formulas"][0]["inference"].pop())
    add("boolean_formula_count", lambda r: r["formulas"][0]["inference"][0].update(count=True))
    add("boolean_forward_count", lambda r: r["formulas"][0]["inference"][0]["cuda"]["inference_implementation"]["actual_forward_calls"].update(output=True))
    add("boolean_decoded_count", lambda r: r["formulas"][0]["inference"][0]["cuda"].update(decoded_count=True))
    add("wrong_formula_device", lambda r: r["formulas"][0]["inference"][0]["cuda"]["inference_implementation"].update(device="cpu"))
    add("selected_without_formula_forward", lambda r: r["formulas"][0]["inference"][0]["cuda"]["inference_implementation"].update(actual_forward_executed=False))
    add("missing_output_head_call", lambda r: r["formulas"][0]["inference"][0]["cuda"]["inference_implementation"]["actual_forward_calls"].update(output=0))
    add("wrong_formula_decision", lambda r: r["formulas"][0]["inference"][0]["cuda"]["rows"][0].update(status="abstained"))
    add("missing_projected_member", lambda r: r["formulas"][0]["inference"][0]["cpu_projected"].clear())
    add("wrong_projected_value", lambda r: r["formulas"][0]["inference"][0]["cuda_projected"][0].__setitem__(0,999.))
    add("missing_native_tamper_control", lambda r: r["controls"].pop())
    add("unrejected_native_tamper", lambda r: r["controls"][0].update(rejected=False))
    with tempfile.TemporaryDirectory(prefix="cuda-reader-path-controls-") as directory:
        base=Path(directory)
        for name,setup in (
                ("root_symlink",lambda: (base/"link").symlink_to(archive,target_is_directory=True)),
                ("file_symlink",lambda: (base/"linkfile").symlink_to(archive/"result.json")),
                ("hardlink",lambda: (base/"hard").hardlink_to(base/"regular"))):
            if name=="hardlink":
                (base/"regular").write_bytes(b"regular")
            setup()
            try:
                reader.audit(base/"link") if name=="root_symlink" else reader._snapshot(base)
            except ValueError as error:
                controls.append({"name":name,"rejected":True,"message":str(error)})
            else:
                raise AssertionError(name+" was accepted")
            if name=="root_symlink":
                (base/"link").unlink()
            elif name=="file_symlink":
                (base/"linkfile").unlink()
    after = reader._snapshot(archive)
    result = {"schema": "native-cuda-reader-guard-controls/v1", "qualified": before == after,
        "cases": len(controls), "failed": 0, "skipped": 0, "errors": 0, "controls": controls,
        "primary_archive_preserved": before == after,
        "reader_sha256": hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest(),
        "guard_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "stdlib_only_closed_receipt_mutation_controls_no_native_jobs",
        "elapsed_seconds": time.monotonic()-started}
    output.write_text(json.dumps(result, sort_keys=True, indent=2))
    output.chmod(0o444)
    print(json.dumps({k:v for k,v in result.items() if k!="controls"},indent=2))


if __name__ == "__main__":
    main()
