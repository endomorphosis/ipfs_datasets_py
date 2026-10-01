"""Exact reversible source joins reuse the existing operational Lean emitter."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import codeunit_program_lean as api
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v4 as executor
from tests.unit.logic.formalization.autoencoder.test_distributed_384_projection_inputs import sample, security_inputs, prepare


def case():
    row = sample("security_ir"); inputs = security_inputs(row)
    source = prepare("security_ir", row, inputs)
    payload = source["typed_inputs"][0].document.to_dict()
    kwargs = dict(code_unit=source["code_unit"], source_text=row["source_text"], candidate=row["target"])
    return payload, kwargs


def test_inverse_join_restores_exact_qualified_original_without_erasing_metadata():
    payload, kwargs = case(); saved = deepcopy(payload)
    original, audit = api.replay_original_program(payload, **kwargs)
    lean, details = api.emit_program(payload, **kwargs)
    assert payload == saved and original["metadata"]["effect_summary_audit"]
    assert audit["inverse_source_join_verified"] and audit["source_candidate_replayed"]
    assert "distributedCodeUnitJoinedProgramJSON" in lean and "sourceEvidenceMetadataJSON" in lean
    assert "sourceEvidenceEffectAuditJSON" in lean and "distributedCodeUnitCandidateJSON" in lean
    assert details["code_unit_evidence_emitted"] and details["source_bytes_replayed"]
    assert not details["candidate_rewritten"] and not details["source_semantics_verified"]
    assert not audit["caller_polarity_verified"]


@pytest.mark.parametrize("change", ["operator", "source", "join", "effects", "metadata", "candidate", "code_unit"])
def test_rehashed_or_structural_tampering_cannot_borrow_a_source_join(change):
    payload, kwargs = case()
    if change == "operator":
        payload["expressions"][-1]["operator"] = "add"
    elif change == "source":
        payload["sources"][0]["content_sha256"] = "f" * 64
    elif change == "join":
        payload["metadata"]["distributed_candidate_source_join"]["original_program_sha256"] = "f" * 64
    elif change == "effects":
        payload["commands"][0]["effects"]["reads"] = []
    elif change == "metadata":
        payload["metadata"]["assumptions"] = []
    elif change == "candidate":
        kwargs["candidate"]["document"]["operator"] = ">"
    else:
        kwargs["code_unit"] = kwargs["code_unit"].to_dict()
        kwargs["code_unit"]["path"] = "another.py"
    with pytest.raises(ValueError):
        api.emit_program(payload, **kwargs)


def test_source_bytes_mutation_rejected_even_if_candidate_still_parses():
    payload, kwargs = case()
    kwargs["source_text"] += "\n"
    with pytest.raises(ValueError):
        api.emit_program(payload, **kwargs)


def test_actual_lake_build_of_codeunit_join_and_operational_model():
    candidates = [Path('/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake'),
                  Path('/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake')]
    lake = next((path for path in candidates if path.is_file()), None)
    if lake is None:
        pytest.skip("native Lake is unavailable")
    payload, kwargs = case()
    source, details = api.emit_program(payload, **kwargs)
    result = executor._execute("namespace CodeUnitJoin\n" + source + "\nend CodeUnitJoin\n", "CodeUnitJoin", str(lake), 30)
    assert result["backend_executed"] and result["status"] == "passed", result
    assert not details["proof_authority"] and not details["source_semantics_verified"]
