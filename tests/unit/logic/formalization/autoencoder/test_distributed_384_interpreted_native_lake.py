"""Extra interpretations must remain bound to the original complete models."""
from copy import deepcopy
import os

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import candidate_native_lake as gate
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import projections_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import digest
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from .test_distributed_384_supplemental_native_lake import source_context, bound_protocol
from .test_family_training_v2 import concurrency_fixtures, protocol_fixtures
from .test_native_concurrency_interpretation import authored_interpretation as concurrency_interpretation
from .test_native_protocol_frames import authored_interpretation as protocol_interpretation
from .test_native_symbolic_refinement_lean import authored_interpretation as refinement_interpretation

FAMILIES = ["concurrency", "cryptographic_protocol", "refinement"]


def original_models():
    row, inputs, source = source_context("security_ir")
    models = {"concurrency": concurrency_fixtures._producer_consumer().to_dict(),
        "refinement": concurrency_fixtures._counter_refinement().to_dict(),
        "protocol": bound_protocol(protocol_fixtures._document().to_dict(), source, row["source_text"])}
    inputs["supplemental_inputs"] = [{"kind": kind, "document": value} for kind, value in models.items()]
    owners = {"concurrency": concurrency_interpretation, "protocol": protocol_interpretation,
              "refinement": refinement_interpretation}
    inputs["supplemental_interpretations"] = [{"kind": kind, "interpretation": owners[kind](model)}
        for kind, model in models.items()]
    return row, inputs


def prepare(row, inputs, families=FAMILIES):
    return api.prepare_candidate_projection("security_ir", row["target"], row["source_text"],
        context=bind_context("security_ir", row["target"], row["source_text"], inputs), required_families=families)


def test_same_native_models_retain_blockers_without_their_explicit_interpretations():
    row, inputs = original_models()
    saved = deepcopy(inputs)
    without = {key: value for key, value in inputs.items() if key != "supplemental_interpretations"}
    baseline = prepare(row, without)
    interpreted = prepare(row, inputs)
    assert not baseline.report["all_requested_dependencies_supported"]
    assert interpreted.report["all_requested_dependencies_supported"]
    assert baseline.native_report == interpreted.native_report
    assert baseline.candidate == interpreted.candidate == row["target"]
    assert inputs == saved
    assert interpreted.report["supplemental_interpretation_count"] == 3
    assert not interpreted.report["supplemental_interpretations_inferred"]
    assert not interpreted.report["proof_authority"] and not interpreted.report["source_semantics_verified"]
    for family in interpreted.report["families"]:
        assert family["native_lowering"][0]["lowering"]["native_document_rewritten"] is False


@pytest.mark.parametrize("change", ["native_hash", "extra_authority", "other_source", "missing_native_view"])
def test_rehashed_context_cannot_change_or_hide_interpretation_boundaries(change):
    row, inputs = original_models()
    if change == "native_hash": inputs["supplemental_interpretations"][0]["interpretation"]["native_document_sha256"] = "0" * 64
    elif change == "extra_authority": inputs["supplemental_interpretations"][0]["interpretation"]["proof_authority"] = True
    elif change == "other_source": row["source_text"] += "\nchanged_source"
    else: inputs["supplemental_inputs"] = inputs["supplemental_inputs"][1:]
    if change == "extra_authority":
        report = prepare(row, inputs).report
        assert not report["all_required_families_supported"]
    else:
        with pytest.raises(ValueError): prepare(row, inputs)


def test_interpretation_for_an_unrequested_view_is_not_silently_discarded():
    row, inputs = original_models()
    with pytest.raises(ValueError, match="no active native projection"):
        prepare(row, inputs, families=["concurrency"])


def test_prepared_handle_returns_detached_interpretation_copies():
    row, inputs = original_models()
    handle = prepare(row, inputs)
    saved = deepcopy(handle.supplemental_interpretations)
    handle.supplemental_interpretations[0]["interpretation"]["native_document_sha256"] = "0" * 64
    handle.report["supplemental_interpretations"].clear()
    inputs["supplemental_interpretations"].clear()
    assert handle.supplemental_interpretations == saved
    assert handle.report["supplemental_interpretation_count"] == 3


def test_real_lake_binds_interpretations_and_retains_a_refuted_protocol_claim(tmp_path):
    lake = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not lake: pytest.skip("installed Lake executable required")
    row, inputs = original_models()
    handle = prepare(row, inputs)
    interpretations = handle.supplemental_interpretations
    execution = gate.build_native_family_lake(handle.native_report, source_inputs=handle.source_inputs,
        source_text=handle.source_text, candidate=handle.candidate, interpretations=interpretations,
        lake_executable=lake, output_directory=tmp_path / "native")
    receipt = gate.verify_native_family_lake(execution, handle.native_report, source_inputs=handle.source_inputs,
        source_text=handle.source_text, candidate=handle.candidate, interpretations=interpretations)
    assert receipt["all_requested_projections_passed"], receipt["execution"]
    assert receipt["supplemental_interpretations_sha256"] == digest(interpretations)
    protocol = next(row for row in receipt["per_projection"] if row["logic_family"] == "cryptographic_protocol")
    observed = protocol["lowering"]["static_frame_interpretation"]["claim_evaluations"]
    assert any(row["counterexample_found"] for row in observed)
    assert all(not row["equivalent_proved"] for row in observed)
    with pytest.raises(ValueError, match="belongs to another"):
        gate.verify_native_family_lake(execution, handle.native_report, source_inputs=handle.source_inputs,
            source_text=handle.source_text, candidate=handle.candidate, interpretations=[])
