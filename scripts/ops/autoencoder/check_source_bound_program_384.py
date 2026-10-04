#!/usr/bin/env python3
"""Replay completed learned SecurityIR candidates through the native Lake gate.

This diagnostic never retrains, edits a prediction, strips program metadata or
executes the Python source. Blocked emitters remain blocked, without compiling
an unrelated empty Lean module to manufacture a success result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(run_directory, output, lake_executable):
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training, native_family_lake_v3
    from ipfs_datasets_py.logic.formalization.autoencoder.security.source_program_binding_384 import verify_source_qualification
    from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
    from ipfs_datasets_py.logic.security_ir.code_logic_projection import CodeLogicEvidence
    from ipfs_datasets_py.logic.security_ir.code_program_derivation import _remap
    from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
    from ipfs_datasets_py.logic.software_verification.program import ProgramIR

    run_directory, output = Path(run_directory).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("fresh diagnostic evidence path required")
    inputs = {name: run_directory / name for name in (
        "freeze.json", "security_ir/test.json", "security_ir/augmented-test-evaluation.json")}
    hashes = {name: _sha(path.read_bytes()) for name, path in inputs.items()}
    sources = json.loads(inputs["security_ir/test.json"].read_text())["rows"]
    evaluation = json.loads(inputs["security_ir/augmented-test-evaluation.json"].read_text())
    source_by_id = {row["id"]: row for row in sources}
    qualification_by_id = {row["id"]: row["qualification"] for row in evaluation["qualifications"]}
    predictions = evaluation["reconstruction"]["rows"]
    selected = {}
    # Cover comparison/arithmetic and direct/temporary return shapes using
    # completed outputs. This is diagnostics, never a new accuracy partition.
    for predicted in predictions:
        source = source_by_id[predicted["id"]]
        checked = qualification_by_id[predicted["id"]]
        target = predicted.get("candidate_ir")
        if checked["status"] != "qualified" or target is None:
            continue
        style = source["wording_style"]
        if style not in (0, 2):
            continue
        selected.setdefault((target["document"]["type_ref"], style), predicted)
    results = []
    for predicted in selected.values():
        source_row = source_by_id[predicted["id"]]
        text = source_row["source_text"]
        raw = text.encode()
        if _sha(raw) != predicted["source_sha256"] or _sha(raw) != source_row["source_sha256"]:
            raise ValueError("completed source identity differs")
        checked = verify_source_qualification(qualification_by_id[predicted["id"]], text, predicted["candidate_ir"])
        program = ProgramIR.from_dict(checked["projections"][0]["native_document"])
        authored = canonical_identity({"row_id": predicted["id"], "source_sha256": _sha(raw)},
            domain="authored-source-ir-diagnostic", schema_version="v1").cid
        body_cid = canonical_identity({"body": text}, domain="cvefixes-security-ir/code-body",
            schema_version="cvefixes-code-body/v1").cid
        unit = CodeUnit(source_cids=(authored,), parent_cids=(authored,), config_cid=authored,
            unit_kind="symbol", language="Python", path="source.py", polarity="fixed",
            payload={"body_sha256": _sha(raw), "body_cid": body_cid,
                     "origin": "authored_development_example", "security_claim": False})
        mapped, source, remapping = _remap(program, unit, raw)
        assert mapped.metadata.to_dict() == program.metadata.to_dict()
        arguments = dict(code_unit=unit, source_bytes=raw,
                         typed_inputs=[CodeLogicEvidence(mapped, source)])
        report = family_training.prepare_family_training_targets("security_ir",
            requested_families=["program"], **arguments)
        execution = native_family_lake_v3.build_native_family_lake(report,
            source_inputs=arguments, lake_executable=lake_executable, timeout_seconds=30)
        receipt = native_family_lake_v3.verify_native_family_lake(execution, report)
        results.append(dict(id=predicted["id"], source_sha256=_sha(raw),
            source_qualification_replayed=True, candidate_sha256=_sha(_bytes(predicted["candidate_ir"])),
            decoder_head_sha256=predicted["head_sha256"], decoder_projection_sha256=predicted["projection_sha256"],
            original_program_id=program.program_id, metadata_preserved=True,
            reference_remapping=remapping, family_report_sha256=report["report_sha256"],
            lake_receipt=receipt))
    if not results:
        raise ValueError("no completed source-qualified representative candidates")
    if any(_sha(path.read_bytes()) != hashes[name] for name, path in inputs.items()):
        raise ValueError("completed benchmark inputs changed during diagnostic")
    receipt = dict(schema="source-bound-program-384-lake-diagnostic/v1", run_directory=str(run_directory),
        diagnostic_source_sha256=_sha(Path(__file__).read_bytes()), input_sha256=hashes,
        selection="first completed candidate per integer/boolean × direct/temporary style",
        count=len(results), passed=sum(row["lake_receipt"]["status"] == "passed" for row in results),
        actual_lake_builds=sum(row["lake_receipt"]["backend_executed"] for row in results), rows=results,
        source_executed=False, training_performed=False, metadata_removed=False,
        proof_authority=False, source_semantics_verified=False, execution_authority=False,
        scope="native program interpretation syntax and types, not Python runtime equivalence or security correctness")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_bytes(receipt))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake-executable", required=True)
    args = parser.parse_args()
    report = run(args.run_directory, args.output, args.lake_executable)
    print(json.dumps({key: report[key] for key in ("count", "passed", "actual_lake_builds")}))
