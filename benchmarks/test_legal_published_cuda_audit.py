"""Stdlib tamper controls for the retained exact public Legal384 replay."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import audit_legal_published_cuda as reader


def main():
    archive,output=Path(sys.argv[1]),Path(sys.argv[2])
    if output.exists():
        raise ValueError("published guard output must be new")
    started=time.monotonic()
    before=reader._snapshot(archive)
    files={name:(archive/name).read_bytes() for name in before}
    record=reader._parse(files["result.json"])
    def load(name):
        if name not in files:
            raise ValueError("artifact outside closed inventory")
        return files[name]
    reader.validate(record,load)
    controls=[]
    def add(name,mutate):
        value=deepcopy(record)
        mutate(value)
        try:
            reader.validate(value,load)
        except (ValueError,KeyError,TypeError) as error:
            controls.append(dict(name=name,rejected=True,message=str(error)))
            return
        raise AssertionError(name+" was accepted")
    add("failed_native",lambda r:r.update(qualified=False))
    add("reported_native_error",lambda r:r.update(error={"type":"failed"}))
    add("unexpected_training",lambda r:r.update(training_calls=1))
    add("boolean_training_counter",lambda r:r.update(training_calls=False))
    add("nonfinite_elapsed",lambda r:r.update(elapsed_seconds=float("inf")))
    add("whole_model_cuda",lambda r:r.update(whole_model_cuda=True))
    add("codebase_semantic_decoder_claim",lambda r:r.update(codebase_384d_qualification=True))
    add("proof_authority",lambda r:r.update(proof_authority=True))
    add("lease_unreleased",lambda r:r.update(own_lease_released=False))
    add("reservation_memory_exceeded",lambda r:r.update(peak_rss_bytes=3*1024**3))
    add("floating_public_revision",lambda r:r["descriptor"].update(revision="main"))
    add("reported_release_dimension",lambda r:r["downloaded_release"].update(dimension=8))
    add("wrong_package_digest",lambda r:r.update(release_package_sha256="0"*64))
    add("wrong_formula_digest",lambda r:r.update(formula_checkpoint_sha256="0"*64))
    add("wrong_retained_adam",lambda r:r["retained_formula_progress"].update(optimizer_steps=0))
    add("missing_producer",lambda r:r["source_pins"].pop())
    add("wrong_frozen_producer",lambda r:r["source_pins"][0].update(sha256="0"*64))
    add("missing_full_batch",lambda r:r["direct_inference"].pop())
    add("boolean_sample_counter",lambda r:r["direct_inference"][0].update(count=True))
    add("boolean_inference_training_steps",lambda r:r["direct_inference"][0]["cpu"].update(training_steps=False))
    add("selection_attests_execution",lambda r:r["direct_inference"][0]["cuda"]["inference_implementation"]["formula_head_selection"].update(cuda_executed=True))
    add("no_actual_cuda_head_forward",lambda r:r["direct_inference"][0]["cuda"]["result"]["inference_implementation"]["formula_decoder"].update(actual_forward_executed=False))
    add("boolean_actual_forward_counter",lambda r:r["direct_inference"][0]["cuda"]["result"]["inference_implementation"]["formula_decoder"]["actual_forward_calls"].update(output=True))
    add("wrong_canonical_decision",lambda r:r["direct_inference"][0]["cuda"]["result"]["rows"][0].update(status="abstained"))
    add("incorrect_source_identity",lambda r:r["source_text_inference"]["cuda"]["result"]["rows"][0].update(source_sha256="0"*64))
    add("pretended_bitwise_latent_identity",lambda r:r["source_text_inference"].update(latent_identity_parity="bitwise"))
    add("incorrect_encoder_tokens",lambda r:r["source_text_inference"]["cuda"]["embedding_execution"]["tokens"][0]["input_ids"].append(123))
    add("cpu_encoder_annotated_cuda",lambda r:r["source_text_inference"]["cpu"]["embedding_execution"].update(cuda_executed=True))
    add("cuda_encoder_actual_output_on_cpu",lambda r:r["source_text_inference"]["cuda"]["embedding_execution"]["actual_forward_batches"][0].update(output_device="cpu"))
    add("false_source_parity_metric",lambda r:r["source_text_inference"].update(max_absolute_error=0.))
    after=reader._snapshot(archive)
    result=dict(schema="published-legal384-cuda-reader-guards/v1",qualified=before==after,
        cases=len(controls),failed=0,errors=0,skipped=0,controls=controls,primary_archive_preserved=before==after,
        reader_sha256=hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest(),
        shared_reader_sha256=hashlib.sha256(Path(reader.__file__).with_name("audit_modal_formula_cuda.py").read_bytes()).hexdigest(),
        guard_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope="stdlib_only_closed_published_receipt_controls_no_native_jobs",elapsed_seconds=time.monotonic()-started)
    output.write_text(json.dumps(result,sort_keys=True,indent=2))
    output.chmod(0o444)
    print({key:value for key,value in result.items() if key!="controls"})


if __name__ == "__main__":
    main()
