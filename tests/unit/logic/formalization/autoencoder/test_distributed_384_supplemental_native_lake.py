"""The complete candidate/source bridge reaches real supplemental semantics."""
from copy import deepcopy
import os

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import projections_v2 as bridge
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder import native_supplemental_lean as routes
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from .test_distributed_384_projection_inputs import sample, unit_for, prepare, security_inputs
from .test_distributed_384_legal_ui_inputs import prepare as legal_ui_prepare
from .test_family_training_v2 import policy
from ipfs_datasets_py.logic.formalization.autoencoder.family_training_v7 import supplemental_source_ref
from ipfs_datasets_py.logic.software_verification.protocol import ProtocolIR
from .test_native_concurrency_lean import fixture as concurrency_fixture
from .test_native_refinement_lean import fixture as refinement_fixture
from .test_native_protocol_lean import fixture as protocol_fixture


KINDS = {"authorization": "authorization", "concurrency": "concurrency",
         "protocol": "cryptographic_protocol", "refinement": "refinement"}


def bound_protocol(payload, source, text):
    """Attach an explicitly authored protocol, without inferring it from code."""
    old_ref = payload["sources"][0]["ref_id"]
    def rebound(value):
        if type(value) is dict:
            if "ref_id" in value and "content_sha256" in value:
                return source.to_dict()
            result = {key: rebound(item) for key, item in value.items()}
            if "start_byte" in result and "end_byte" in result:
                result.update(start_byte=0, end_byte=len(text.encode()))
            return result
        if type(value) is list: return [rebound(item) for item in value]
        return source.ref_id if value == old_ref else value
    wire = rebound(payload); wire["document_id"] = ""
    return ProtocolIR.from_dict(wire).to_dict()


def source_context(domain):
    row = sample(domain)
    if domain == "security_ir":
        inputs = {"code_unit": unit_for(row["source_text"]).to_dict()}
        native = prepare(domain, row, inputs)
    elif domain == "intent_ir":
        inputs = {}; native = prepare(domain, row, inputs)
    else:
        inputs = {}; native = legal_ui_prepare(domain, row["target"], row["source_text"])
    source = supplemental_source_ref(domain, **native)
    return row, inputs, source


def context_models(domain="security_ir"):
    row, inputs, source = source_context(domain)
    models = {"authorization": policy(source).to_dict()}
    if domain == "security_ir":
        models.update(concurrency=concurrency_fixture(),
            protocol=bound_protocol(protocol_fixture(), source, row["source_text"]),
            refinement=refinement_fixture().to_dict())
    inputs["supplemental_inputs"] = [{"kind": kind, "document": value} for kind, value in models.items()]
    return row, inputs


def prepared(domain="security_ir", *, inputs=None, families=None):
    row, default_inputs = context_models(domain)
    if inputs is None: inputs = default_inputs
    if families is None: families = sorted(KINDS.values()) if domain == "security_ir" else ["authorization"]
    return bridge.prepare_candidate_projection(domain, row["target"], row["source_text"],
        context=bind_context(domain, row["target"], row["source_text"], inputs), required_families=families)


@pytest.mark.parametrize("domain", ["intent_ir", "security_ir", "ui_ux_ir", "legal_ir"])
def test_authorization_is_connected_to_each_applicable_native_domain(domain):
    result = prepared(domain, families=["authorization"])
    report = result.report
    assert report["all_required_families_supported"]
    family = report["families"][0]
    assert family["projections"][0]["projection_id"] == domain + "/supplemental/authorization/v2"
    lowered = family["native_lowering"][0]
    assert lowered["lowering"]["supplemental_kind"] == "authorization"
    assert lowered["previous_lowering_observation"]["semantic_lowering_supported"] is False
    assert not report["context_inferred_by_model"] and not report["source_semantics_verified"]
    assert not lowered["lowering"]["authorization_granted"]


def test_all_four_closed_fragments_keep_original_source_candidate_and_reports():
    row, inputs = context_models()
    saved = deepcopy(inputs)
    result = prepared(inputs=inputs)
    assert inputs == saved
    assert result.report["all_requested_dependencies_supported"]
    assert result.report["candidate_sha256"] == bind_context("security_ir", row["target"], row["source_text"], inputs)["candidate_sha256"]
    assert all(f["native_lowering"][0]["semantic_lowering_supported"] for f in result.report["families"])
    for family in result.report["families"]:
        details = family["native_lowering"][0]["lowering"]
        assert details["native_document_rewritten"] is False
        assert details["source_meaning_inferred"] is False
        assert details["capability_floor_eligible"] is False


def test_real_lake_build_of_program_and_all_four_new_families(tmp_path):
    executable = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not executable: pytest.skip("Set IR384_TEST_LAKE_EXECUTABLE to execute native build")
    result = prepared(families=["program", *KINDS.values()])
    report = bridge.check_candidate_projection(result, lake_executable=executable, output_directory=tmp_path / "native")
    assert report["lake_build_executed"] and report["all_requested_native_checks_passed"], report["native_execution"]["execution"]
    assert report["native_execution"]["extended_projection_count"] == 5
    assert len(report["native_execution"]["per_projection"]) == 5
    assert not report["proof_authority"] and not report["source_semantics_verified"]


@pytest.mark.parametrize("kind", ["concurrency", "refinement", "protocol"])
def test_previous_richer_examples_stay_blocked_and_other_supported_views_remain(kind):
    from .test_family_training_v2 import concurrency_fixtures, protocol_fixtures
    original = {"concurrency": concurrency_fixtures._producer_consumer,
                "refinement": concurrency_fixtures._counter_refinement,
                "protocol": protocol_fixtures._document}[kind]()
    row, inputs = context_models()
    _, _, source = source_context("security_ir")
    for item in inputs["supplemental_inputs"]:
        if item["kind"] == kind:
            item["document"] = (bound_protocol(original.to_dict(), source, row["source_text"])
                if kind == "protocol" else original.to_dict())
    result = prepared(inputs=inputs).report
    families = {item["family_id"]: item for item in result["families"]}
    assert families[KINDS[kind]]["status"] == "missing_context"
    assert families["authorization"]["status"] == "supported"
    assert not result["all_required_families_supported"]
    observation = families[KINDS[kind]]["native_lowering"][0]
    assert observation["attempted_extension"] == "native_supplemental"
    assert observation["reason"] and observation["previous_lowering_observation"]


@pytest.mark.parametrize("field", ["projection_id", "logic_family", "profile"])
def test_route_spoofing_cannot_relabel_model_semantics(field):
    result = prepared()
    projection = deepcopy(result.native_report["projections"][0])
    projection[field] = "wrong"
    with pytest.raises(UnsupportedNativeLean): routes.emit_projection(projection, domain="security_ir")


def test_extra_bridge_fields_and_unknown_native_fields_are_never_silently_ignored():
    result = prepared()
    projection = deepcopy(result.native_report["projections"][0])
    projection["payload"]["ignored"] = True
    with pytest.raises(UnsupportedNativeLean): routes.emit_projection(projection, domain="security_ir")
    row, inputs = context_models()
    inputs["supplemental_inputs"][0]["document"]["extra_obligation"] = "secret"
    with pytest.raises(ValueError): prepared(inputs=inputs)


def test_bound_native_policy_cannot_borrow_another_source_identity():
    _, inputs = context_models()
    inputs["supplemental_inputs"][0]["document"]["sources"][0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError): prepared(inputs=inputs)
