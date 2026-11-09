"""Synthetic parent-definition review authenticates custody, never legal meaning.

Existing plaintext fixtures provide the original physical evidence and all
context packets. Existing review fixtures provide real Ed25519 signatures and
explicit synthetic trust; no annotation or statutory acceptance is invented.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as owner
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parent_owner
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2 as bridge
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as official_context
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


@pytest.fixture(scope="module")
def fixtures():
    spec = importlib.util.spec_from_file_location(
        "parent_definition_review_existing_context_fixture",
        Path(__file__).with_name("test_plaintext_context_custody.py"))
    assert spec is not None and spec.loader is not None
    context = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(context)
    definition = context.fixtures.__wrapped__()
    review = definition.helper("test_corpus_definition_review_v2")
    return SimpleNamespace(context=context, definition=definition, review=review)


def make_case(fixtures, parent, *, family="fol", parent_index=0):
    definition = fixtures.definition
    request, inputs = definition.case(parent, family=family, parent_index=parent_index)
    request["declaration"]["contributor_spans"].append(definition.interval(
        definition.TEXT, definition.TEXT.rindex("registered"), len(definition.TEXT)))
    report = bridge.prepare_parent_definition_v1(request, **inputs)
    candidate, report_raw, _ = definition.adapt(report, request, inputs)
    request_raw = definition.wire(request)
    candidate_raw = canonical_dag_json_bytes(candidate)
    binding = report["parent_source_binding"]
    pins = {
        "candidate_sha256": definition.sha(candidate_raw),
        "candidate_cid": candidate["record_cid"],
        "graph_cid": candidate["graph"]["record_cid"],
        "request_sha256": definition.sha(request_raw),
        "report_sha256": definition.sha(report_raw),
        "parent_manifest_cid": inputs["expected_manifest_cid"],
        "source_binding_sha256": binding["source_binding_sha256"],
        "root_source_occurrence_cid": inputs["source_occurrence_cid"],
        "companion_record_cid": inputs["companion_record_cid"],
        "source_version_cid": candidate["source_version"]["record_cid"],
        "extracted_sha256": candidate["source_version"]["extracted_view"]["sha256"],
    }
    definition_case = {"report": report, "request": request,
        "inputs": inputs, "candidate": candidate}
    packets, population = [], []
    for occurrence in candidate["source_occurrences"]:
        packet = fixtures.context.build(definition_case, occurrence)
        raw = definition.wire(packet)
        packets.append({"source_occurrence_cid": occurrence["record_cid"],
            "packet_raw": raw, "dependency_requests": None})
        population.append({"source_occurrence_cid": occurrence["record_cid"],
            "packet_sha256": definition.sha(raw)})
    return {"record": candidate, "report": report, "request": request,
        "arguments": {
            "candidate_inputs": {"candidate_raw": candidate_raw,
                "report_raw": report_raw, "request_raw": request_raw},
            "expected_candidate_pin": pins, "parent_inputs": inputs,
            "context_inputs": packets, "expected_context_population": population}}


def materialize(case):
    args = case["arguments"]
    preparation = owner.prepare_parent_definition_review_evidence_v1(**args)
    manifest = dependencies.build_dependency_manifest(preparation["artifacts"],
        preparation["edges"], expected_artifact_ids=preparation["expected_artifact_ids"])
    subject = owner.build_parent_definition_review_subject_v1(preparation, manifest,
        **args, expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=preparation["expected_artifact_ids"])
    return {"case": case, "arguments": args, "preparation": preparation,
        "manifest": manifest, "subject": subject}


@pytest.fixture(scope="module")
def parent(fixtures, tmp_path_factory):
    return fixtures.definition.parent_case.__wrapped__(
        tmp_path_factory.mktemp("parent-definition-review-originals", numbered=False))


@pytest.fixture(scope="module")
def base_case(fixtures, parent):
    return make_case(fixtures, parent)


@pytest.fixture(scope="module")
def base_materialized(base_case):
    return materialize(base_case)


@pytest.fixture
def case(base_case):
    return deepcopy(base_case)


@pytest.fixture
def signed(fixtures, base_materialized):
    domain = SimpleNamespace(CLAIM_SCHEMA=owner.PARENT_CLAIM_SCHEMA,
        ACTION=owner.PARENT_ACTION, AUDIENCE=owner.PARENT_AUDIENCE)
    return fixtures.review.signed.__wrapped__(domain, base_materialized)


def assess(fixtures, data):
    args, kwargs = fixtures.review.assessment_arguments(data)
    return owner.assess_parent_definition_reviews_v1(*args, **kwargs)


def replace_candidate(fixtures, case, record):
    record = fixtures.definition.reseal(record)
    raw = canonical_dag_json_bytes(record)
    case["record"] = record
    case["arguments"]["candidate_inputs"]["candidate_raw"] = raw
    case["arguments"]["expected_candidate_pin"].update(
        candidate_sha256=fixtures.definition.sha(raw), candidate_cid=record["record_cid"])


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_full_plaintext_subject_preserves_all_occurrences_contexts_and_unknown_edition(
        fixtures, parent, base_case, family, monkeypatch):
    def no_markup(*args, **kwargs):
        pytest.fail("parent-definition review must not extract or synthesize markup")
    monkeypatch.setattr(official_context, "extract_document", no_markup)
    case = deepcopy(base_case) if family == "fol" else make_case(fixtures, parent, family=family)
    before = deepcopy(case)
    data = materialize(case)
    record, prep, subject = case["record"], data["preparation"], data["subject"]
    assert prep["schema"] == owner.PARENT_PREPARATION_SCHEMA
    assert subject["schema"] == owner.PARENT_SUBJECT_SCHEMA != owner.SUBJECT_SCHEMA
    assert prep["family"] == family and prep["native_ast"] == record["ast_record"]["native_ast"]
    assert prep["source_occurrences"] == record["source_occurrences"]
    assert prep["parent_source_binding"] == record["parent_source_binding"]
    assert prep["source_version"]["edition"] == parent_owner.UNDECLARED_EDITION
    assert prep["source_version"]["raw_artifact"]["media_type"] == "text/plain"
    assert prep["source_version"]["extracted_view"]["normalization_profile"] == "identity/v1"
    assert prep["contributor_completeness_verified"] is False
    assert prep["governing_scope_verified"] is False
    assert prep["source_region_roles_verified"] is False
    assert record["input_binding"]["contributor_spans"] == case["request"]["declaration"]["contributor_spans"]
    assert len(record["input_binding"]["contributor_spans"]) == 2
    occurrences = record["source_occurrences"]
    expected_ids = [row["record_cid"] for row in occurrences]
    assert len(expected_ids) == len(set(expected_ids))
    root_cid = case["arguments"]["expected_candidate_pin"]["root_source_occurrence_cid"]
    assert root_cid in expected_ids and any(cid != root_cid for cid in expected_ids)
    assert any("\n" in row["span_text"] for row in occurrences)
    assert [row["source_occurrence_cid"] for row in prep["expected_context_population"]] == expected_ids
    slots = []
    for occurrence, offered in zip(occurrences, data["arguments"]["context_inputs"], strict=True):
        packet = json.loads(offered["packet_raw"])
        assert packet["selection"] == occurrence
        assert packet["original_context"]["availability"] == "required_unavailable"
        assert packet["original_context"]["missing_requirements"] == list(parent_owner.MISSING_CONTEXT)
        start, end = occurrence["start_char"], occurrence["end_char"]
        assert occurrence["span_text"] == fixtures.definition.TEXT[start:end]
        assert occurrence["start_utf8"] == len(fixtures.definition.TEXT[:start].encode())
        assert occurrence["end_utf8"] == len(fixtures.definition.TEXT[:end].encode())
        assert all(slot["open"] and not slot["attachments"] for slot in packet["dependency_slots"])
        slots.extend(slot["slot_id"] for slot in packet["dependency_slots"])
    assert len(slots) == len(set(slots)) == 6 * len(occurrences)
    assert subject["context_slot_ids"] == slots
    assert subject["required_dependency_ids"] == prep["expected_artifact_ids"]
    assert subject["native_binding"] == prep
    assert all(prep[key] is False for key in owner.FALSE_FLAGS)
    assert owner.validate_parent_definition_review_evidence_v1(prep, **data["arguments"]) == prep
    assert case == before


def test_public_review_preparation_replays_original_physical_parent(fixtures, case, monkeypatch):
    original = parent_owner.validate_parent_occurrence_corpus
    calls = []
    inputs = case["arguments"]["parent_inputs"]
    def observed(bundle, **kwargs):
        assert bundle == inputs["parent_bundle"]
        assert kwargs["report_bytes"] == inputs["report_bytes"]
        assert kwargs["replay_inputs"] == inputs["replay_inputs"]
        calls.append(bundle["manifest"]["record_cid"])
        return original(bundle, **kwargs)
    monkeypatch.setattr(parent_owner, "validate_parent_occurrence_corpus", observed)
    owner.prepare_parent_definition_review_evidence_v1(**case["arguments"])
    assert calls and set(calls) == {inputs["expected_manifest_cid"]}


def test_real_synthetic_signatures_authenticate_parent_domain_without_meaning(fixtures, signed):
    assert owner.PARENT_CLAIM_SCHEMA != owner.CLAIM_SCHEMA
    assert owner.PARENT_ACTION != owner.ACTION
    assert owner.PARENT_AUDIENCE != owner.AUDIENCE
    result = assess(fixtures, signed)
    assert result["schema"] == owner.PARENT_SCHEMA
    assert result["evidence_assessment_status"] == "authenticated"
    assert result["authenticated_evidence_count"] == 2
    assert all(row["signed_context_declaration_complete"] for row in result["reviews"])
    assert "production_trust_registry_unavailable" in result["blockers"]
    assert result["accepted_view_eligible"] is False
    assert all(result[key] is False for key in signatures.FALSE_AUTHORITY)
    args, kwargs = fixtures.review.assessment_arguments(signed)
    assert owner.validate_parent_definition_review_assessment_v1(result, *args, **kwargs) == result


def test_external_trust_shape_still_grants_no_human_semantic_or_lean_authority(fixtures, signed):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    fixtures.review.refresh(signed)
    result = assess(fixtures, signed)
    assert result["review_prerequisites_satisfied_under_selected_trust"] is True
    assert result["accepted_view_eligible"] is False
    assert all(result[key] is False for key in signatures.FALSE_AUTHORITY)
    assert "downstream_semantic_validation_required" in result["blockers"]
    assert "downstream_Lean_kernel_admission_required" in result["blockers"]


@pytest.mark.parametrize("damage", ["omit", "reverse", "duplicate", "unknown_field"])
def test_context_inputs_and_independent_population_keep_exact_candidate_order(case, damage):
    args = case["arguments"]
    packets, population = args["context_inputs"], args["expected_context_population"]
    if damage == "omit":
        packets.pop()
        population.pop()
    elif damage == "reverse":
        packets.reverse()
        population.reverse()
    elif damage == "duplicate":
        packets[-1] = deepcopy(packets[0])
        population[-1] = deepcopy(population[0])
    else:
        packets[0]["reviewed"] = True
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_review_evidence_v1(**args)


@pytest.mark.parametrize("population,damage", [
    ("source_occurrences", "omit"), ("source_occurrences", "reverse"),
    ("source_occurrences", "duplicate"), ("contributors", "omit"),
    ("contributors", "reverse"), ("contributors", "duplicate"),
])
def test_resealed_candidate_cannot_replace_original_source_or_contributor_population(
        fixtures, case, population, damage):
    record = deepcopy(case["record"])
    rows = record["source_occurrences"] if population == "source_occurrences" else record["input_binding"]["contributor_spans"]
    assert len(rows) > 1
    if damage == "omit":
        rows.pop()
    elif damage == "reverse":
        rows.reverse()
    else:
        rows[-1] = deepcopy(rows[0])
    if population == "contributors":
        record["input_binding"] = fixtures.definition.reseal(record["input_binding"])
    replace_candidate(fixtures, case, record)
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_review_evidence_v1(**case["arguments"])


def test_resealed_native_ast_cannot_weaken_original_definition(fixtures, case):
    record = deepcopy(case["record"])
    record["ast_record"]["native_ast"]["formula"]["operator"]["value"] = "→"
    record["ast_record"] = fixtures.definition.reseal(record["ast_record"])
    replace_candidate(fixtures, case, record)
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_review_evidence_v1(**case["arguments"])


@pytest.mark.parametrize("damage", ["UTF8", "omit_slot", "false_closure"])
def test_rehashed_context_packets_cannot_retarget_geometry_or_close_obligations(fixtures, case, damage):
    args = case["arguments"]
    offered = args["context_inputs"][0]
    packet = json.loads(offered["packet_raw"])
    if damage == "UTF8":
        packet["selection"]["start_utf8"] += 1
        packet["selection"]["end_utf8"] += 1
        packet["selection"] = fixtures.definition.reseal(packet["selection"])
    elif damage == "omit_slot":
        packet["dependency_slots"].pop()
    else:
        packet["context_closure_verified"] = True
    fixtures.context.repair_packet_id(packet)
    offered["packet_raw"] = fixtures.definition.wire(packet)
    args["expected_context_population"][0]["packet_sha256"] = fixtures.definition.sha(offered["packet_raw"])
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_review_evidence_v1(**args)


@pytest.mark.parametrize("field", ["candidate_sha256", "source_binding_sha256", "root_source_occurrence_cid"])
def test_independent_candidate_and_parent_binding_pins_remain_required(case, field):
    pins = case["arguments"]["expected_candidate_pin"]
    pins[field] = case["record"]["request_record"]["record_cid"] if field.endswith("_cid") else "0" * 64
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_review_evidence_v1(**case["arguments"])


@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_validly_signed_official_domain_is_not_parent_review(fixtures, signed, field):
    signed["reviews"][0][field] = {"schema": owner.CLAIM_SCHEMA,
        "action": owner.ACTION, "audience": owner.AUDIENCE}[field]
    fixtures.review.refresh(signed)
    with pytest.raises(ValueError):
        assess(fixtures, signed)


@pytest.mark.parametrize("damage,blocker", [
    ("signature", "signature_invalid"), ("key_revoked", "key_revoked"),
    ("expired_review", "review_not_current"),
])
def test_existing_authenticator_rechecks_signature_revocation_and_time(fixtures, signed, damage, blocker):
    if damage == "signature":
        signed["reviews"][0]["interpretation"]["rationale"] += " unsigned mutation"
    else:
        if damage == "key_revoked":
            signed["registry"]["keys"][0]["revoked_at_utc"] = fixtures.review.NOW
        else:
            signed["reviews"][0]["expires_at_utc"] = fixtures.review.NOW
        fixtures.review.refresh(signed)
    result = assess(fixtures, signed)
    assert result["reviews"][0]["status"] == "rejected"
    assert blocker in result["reviews"][0]["blockers"]
    assert result["accepted_view_eligible"] is False


@pytest.mark.parametrize("damage", ["artifact", "owner_pin"])
def test_current_artifact_and_owner_observations_are_required_even_for_signed_claims(fixtures, signed, damage):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    fixtures.review.refresh(signed)
    if damage == "artifact":
        signed["observed_artifact_sha256s"][signed["preparation"]["expected_artifact_ids"][-1]] = "0" * 64
    else:
        kind, pin = next((kind, pin) for artifact in signed["manifest"]["artifacts"]
            for kind, pins in artifact["dependency_pins"].items() for pin in pins)
        signed["observed_pins"][kind][pin["key"]] = "0" * 64
    result = assess(fixtures, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "required_dependency_closure_not_current" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False


def test_resigned_subject_cannot_omit_required_context_population(fixtures, signed):
    signed["subject"]["context_slot_ids"].pop()
    for claim in signed["reviews"]:
        claim["subject"] = deepcopy(signed["subject"])
    fixtures.review.refresh(signed)
    with pytest.raises(ValueError):
        assess(fixtures, signed)


def test_saved_review_custody_refuses_changed_physical_parent(fixtures, tmp_path):
    parent = fixtures.definition.parent_case.__wrapped__(tmp_path)
    case = make_case(fixtures, parent)
    prep = owner.prepare_parent_definition_review_evidence_v1(**case["arguments"])
    descriptor = case["arguments"]["parent_inputs"]["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
    path = Path(descriptor["local_path"])
    path.write_bytes(path.read_bytes() + b"changed isolated review fixture")
    with pytest.raises(ValueError):
        owner.validate_parent_definition_review_evidence_v1(prep, **case["arguments"])


def test_rehashed_assessment_cannot_promote_synthetic_review_to_meaning(fixtures, signed):
    result = assess(fixtures, signed)
    result["accepted_view_eligible"] = result["source_semantics_verified"] = True
    result["assessment_sha256"] = signatures.digest({key: value for key, value in result.items()
        if key != "assessment_sha256"})
    args, kwargs = fixtures.review.assessment_arguments(signed)
    with pytest.raises(ValueError):
        owner.validate_parent_definition_review_assessment_v1(result, *args, **kwargs)


@pytest.mark.parametrize("damage", ["candidate_oversize", "context_population_oversize", "unknown_parent_limit"])
def test_closed_bounded_evidence_refuses_without_silent_truncation(case, damage, monkeypatch):
    args = case["arguments"]
    if damage == "candidate_oversize":
        args["candidate_inputs"]["candidate_raw"] = b" " * (contracts.MAX_RECORD_BYTES + 1)
    elif damage == "context_population_oversize":
        args["context_inputs"] = [deepcopy(args["context_inputs"][0]) for _ in range(owner.MAX_CONTEXT_OCCURRENCES + 1)]
        args["expected_context_population"] = [deepcopy(args["expected_context_population"][0])
            for _ in range(owner.MAX_CONTEXT_OCCURRENCES + 1)]
    else:
        args["parent_limits"] = {"ignored_limit": 1}
    if damage != "unknown_parent_limit":
        def no_parent_replay(*args, **kwargs):
            pytest.fail("oversized review intake must refuse before original parent replay")
        monkeypatch.setattr(parent_owner, "validate_parent_occurrence_corpus", no_parent_replay)
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_review_evidence_v1(**args)


def test_absent_review_remains_pending_with_explicit_unavailable_trust(fixtures, signed):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "unavailable"
    signed["registry"]["keys"] = []
    signed["reviews"] = []
    fixtures.review.refresh(signed)
    result = assess(fixtures, signed)
    assert result["evidence_assessment_status"] == "pending"
    assert result["authenticated_evidence_count"] == 0
    assert "trust_registry_unavailable" in result["blockers"]
    assert all(result[key] is False for key in signatures.FALSE_AUTHORITY)


def test_equal_text_from_another_physical_parent_cannot_replace_review_context(fixtures, parent, case):
    other = make_case(fixtures, parent, parent_index=1)
    assert other["record"]["source_version"]["extracted_view"]["sha256"] == case["record"]["source_version"]["extracted_view"]["sha256"]
    assert other["record"]["source_version"]["record_cid"] != case["record"]["source_version"]["record_cid"]
    case["arguments"]["context_inputs"] = other["arguments"]["context_inputs"]
    case["arguments"]["expected_context_population"] = other["arguments"]["expected_context_population"]
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_review_evidence_v1(**case["arguments"])
