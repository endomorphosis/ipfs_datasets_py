"""Plaintext combined-use review binds custody, never statutory authority.

Authored plaintext and complete parent replay come from the existing use
fixtures. Real signatures use the existing explicitly synthetic credentials.
No model, markup extraction, legal annotation or Lean execution is performed.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as endpoint_review
from ipfs_datasets_py.logic.autoformal import corpus_definition_use_review_v2 as owner
from ipfs_datasets_py.logic.autoformal import corpus_definition_use_v2 as use
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parents
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as markup
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def reseal(record):
    return contracts.seal_record({key: value for key, value in record.items()
                                 if key not in {"record_cid", "cid_scope"}})


@pytest.fixture(scope="module")
def fixtures():
    path = Path(__file__).with_name("test_plaintext_definition_use.py")
    spec = importlib.util.spec_from_file_location("parent_use_review_existing_fixture", path)
    assert spec is not None and spec.loader is not None
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    return SimpleNamespace(source=source, data=source.fixtures.__wrapped__(),
        signing=source.helper("test_corpus_definition_review_v2"))


def component(fixtures, path, *, family="fol"):
    data = fixtures.source.make_case(fixtures.data, path, family=family)
    request_raw, kwargs = fixtures.source.arguments(data)
    record = use.prepare_parent_definition_use_v1(request_raw, **kwargs)
    raw = canonical_dag_json_bytes(record)
    return {"case": data, "record": record, "component_raw": raw,
        "expected_component_pin": {
            "component_sha256": sha(raw), "component_cid": record["record_cid"],
            "graph_cid": record["graph"]["record_cid"],
            "joint_ast_sha256": sha(canonical_dag_json_bytes(record["joint_native"]["native_ast"]))},
        "use_inputs": {"request_raw": request_raw, **kwargs}}


def arguments(data):
    return {key: data[key] for key in
            ("component_raw", "expected_component_pin", "use_inputs")}


def materialize(data):
    args = arguments(data)
    preparation = owner.prepare_parent_definition_use_review_evidence_v1(**args)
    manifest = dependencies.build_dependency_manifest(preparation["artifacts"],
        preparation["edges"], expected_artifact_ids=preparation["expected_artifact_ids"])
    subject = owner.build_parent_definition_use_review_subject_v1(preparation, manifest,
        **args, expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=preparation["required_dependency_ids"])
    return {"component": data, "arguments": args, "preparation": preparation,
            "manifest": manifest, "subject": subject}


@pytest.fixture(scope="module")
def base_component(fixtures, tmp_path_factory):
    return component(fixtures,
        tmp_path_factory.mktemp("parent-use-review-originals", numbered=False))


@pytest.fixture
def case(base_component):
    return deepcopy(base_component)


@pytest.fixture(scope="module")
def base_materialized(base_component):
    return materialize(base_component)


@pytest.fixture
def signed(fixtures, base_materialized):
    domain = SimpleNamespace(CLAIM_SCHEMA=owner.PARENT_CLAIM_SCHEMA,
        ACTION=owner.PARENT_ACTION, AUDIENCE=owner.PARENT_AUDIENCE)
    return fixtures.signing.signed.__wrapped__(domain, base_materialized)


def assess(fixtures, data):
    args, kwargs = fixtures.signing.assessment_arguments(data)
    return owner.assess_parent_definition_use_reviews_v1(*args, **kwargs)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_combined_subject_preserves_sources_roles_contexts_and_unknown_editions(
        fixtures, tmp_path, base_component, family, monkeypatch):
    def no_markup(*args, **kwargs):
        pytest.fail("plaintext combined review must not extract or synthesize markup")
    monkeypatch.setattr(markup, "extract_document", no_markup)
    data = deepcopy(base_component) if family == "fol" else component(fixtures, tmp_path, family=family)
    before = deepcopy(data)
    prepared = materialize(data)
    record, prep, subject = data["record"], prepared["preparation"], prepared["subject"]
    assert prep["schema"] == owner.PARENT_PREPARATION_SCHEMA
    assert subject["schema"] == owner.PARENT_SUBJECT_SCHEMA != owner.SUBJECT_SCHEMA
    assert prep["review_profile"] == owner.PARENT_PROFILE
    assert prep["profile"] == use.PARENT_PROFILE and prep["family"] == family
    assert prep["native_ast"] == record["joint_native"]["native_ast"]
    assert prep["ast_sha256"] == sha(canonical_dag_json_bytes(record["joint_native"]["native_ast"]))
    assert prep["binding_record"] == record["binding_record"]
    assert prep["alias_record"] == record["alias_record"]
    assert prep["alias_record"]["assumed_not_proved"] is True
    assert prep["binding_record"]["body_roles"] == ["definition_body/0000", "definition_body/0001"]
    assert len(set(prep["binding_record"]["body_occurrence_cids"])) == 2
    assert prep["contexts"] == record["context_population"]
    slots = [slot["slot_id"] for row in prep["contexts"]
             for slot in row["context"]["dependency_slots"]]
    assert slots == prep["context_slot_ids"] == subject["context_slot_ids"]
    assert len(slots) == len(set(slots)) == 6 * len(prep["contexts"])
    assert all(slot["open"] and not slot["attachments"] for row in prep["contexts"]
               for slot in row["context"]["dependency_slots"])
    assert [row["role"] for row in prep["original_definitions"]] == ["donor", "consumer"]
    original_scopes, source_ids = [], []
    for row in prep["original_definitions"]:
        original = data["case"][row["role"]]["candidate"]
        assert row["source_version"] == original["source_version"]
        assert row["scope_record"] == original["scope_record"]
        assert row["source_bindings"] == original["source_bindings"]
        assert row["source_version"]["edition"] == parents.UNDECLARED_EDITION
        assert row["source_version"]["raw_artifact"]["media_type"] == "text/plain"
        assert row["source_version"]["extracted_view"]["normalization_profile"] == "identity/v1"
        original_scopes.append(row["scope_record"]["record_cid"])
        source_ids.append(row["source_version"]["record_cid"])
    assert len(set(source_ids)) == 2
    assert subject["scope_id"] == prep["scope_binding"]["record_cid"]
    assert subject["scope_id"] not in original_scopes
    scope_bytes = wire(prep["scope_binding"]).decode()
    assert all(identity in scope_bytes for identity in original_scopes + source_ids)
    assert parents.UNDECLARED_EDITION in scope_bytes
    assert "declared_applicability" not in prep["scope_binding"]
    assert all(prep[key] is False for key in owner.FALSE_FLAGS)
    for key in ("governing_scope_verified", "governing_edition_verified",
                "contributor_completeness_verified", "source_region_roles_verified"):
        assert prep[key] is False
    assert prep["review_contract"]["original_endpoint_reviews_authorize_combination"] is False
    assert prep["review_contract"]["alias_assumed_not_proved"] is True
    assert subject["native_binding"] == prep
    assert subject["required_dependency_ids"] == prep["required_dependency_ids"]
    original_manifest = record["dependency_manifest"]
    assert prep["artifacts"][:len(original_manifest["artifacts"])] == original_manifest["artifacts"]
    assert prep["edges"][:len(original_manifest["edges"])] == original_manifest["edges"]
    assert data == before


def test_parent_combined_synthetic_signatures_grant_no_semantic_or_lean_authority(fixtures, signed):
    assert owner.PARENT_CLAIM_SCHEMA not in {owner.CLAIM_SCHEMA, endpoint_review.PARENT_CLAIM_SCHEMA}
    assert owner.PARENT_ACTION not in {owner.ACTION, endpoint_review.PARENT_ACTION}
    assert owner.PARENT_AUDIENCE not in {owner.AUDIENCE, endpoint_review.PARENT_AUDIENCE}
    result = assess(fixtures, signed)
    assert result["schema"] == owner.PARENT_SCHEMA
    assert result["evidence_assessment_status"] == "authenticated"
    assert result["authenticated_evidence_count"] == 2
    assert all(row["signed_context_declaration_complete"] for row in result["reviews"])
    assert "production_trust_registry_unavailable" in result["blockers"]
    assert result["accepted_view_eligible"] is False
    assert all(result[key] is False for key in signatures.FALSE_AUTHORITY)
    for key in ("governing_scope_verified", "governing_edition_verified",
                "contributor_completeness_verified", "source_region_roles_verified"):
        assert result[key] is False
    args, kwargs = fixtures.signing.assessment_arguments(signed)
    assert owner.validate_parent_definition_use_review_assessment_v1(result, *args, **kwargs) == result


def test_parent_component_transport_remains_distinct_from_full_canonical_identity(case):
    canonical_hash = sha(canonical_dag_json_bytes(case["record"]))
    case["component_raw"] = wire(case["record"]) + b"\n"
    transport_hash = sha(case["component_raw"])
    assert canonical_hash != transport_hash
    case["expected_component_pin"]["component_sha256"] = transport_hash
    prep = owner.prepare_parent_definition_use_review_evidence_v1(**arguments(case))
    assert prep["component_pin"]["component_sha256"] == transport_hash
    assert prep["component_canonical_sha256"] == canonical_hash
    assert prep["graph_id"] == case["record"]["graph"]["record_cid"]
    assert prep["ast_sha256"] == case["expected_component_pin"]["joint_ast_sha256"]
    artifacts = {row["artifact_id"]: row for row in prep["artifacts"]}
    assert artifacts[case["record"]["record_cid"]]["artifact_sha256"] == transport_hash
    assert any(row["artifact_sha256"] == canonical_hash and identity != case["record"]["record_cid"]
               for identity, row in artifacts.items())


@pytest.mark.parametrize("field", ["component_sha256", "component_cid", "graph_cid", "joint_ast_sha256"])
def test_every_independent_parent_component_pin_is_required(fixtures, case, field):
    case["expected_component_pin"][field] = (
        fixtures.source.cid("foreign-parent-review-component") if field.endswith("_cid") else "0" * 64)
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_use_review_evidence_v1(**arguments(case))


@pytest.mark.parametrize("damage", ["query_pin", "source_pin", "omitted_context"])
def test_parent_combined_review_replays_lookup_and_original_endpoint_custody(case, damage):
    replay = case["use_inputs"]
    if damage == "query_pin":
        replay["expected_query_sha256"] = "0" * 64
    elif damage == "source_pin":
        replay["donor_evidence_inputs"]["expected_candidate_pin"]["source_binding_sha256"] = "0" * 64
    else:
        evidence = replay["consumer_evidence_inputs"]
        evidence["context_inputs"].pop()
        evidence["expected_context_population"].pop()
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_use_review_evidence_v1(**arguments(case))


def test_resealed_alias_cannot_replace_original_joint_assumption(case):
    record = case["record"]
    record["alias_native"]["native_ast"]["formula"]["operator"]["value"] = "→"
    record = reseal(record)
    case["component_raw"] = canonical_dag_json_bytes(record)
    case["expected_component_pin"].update(component_sha256=sha(case["component_raw"]),
        component_cid=record["record_cid"])
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_use_review_evidence_v1(**arguments(case))


def test_saved_parent_combined_review_refuses_changed_physical_source(fixtures, tmp_path):
    data = component(fixtures, tmp_path)
    prep = owner.prepare_parent_definition_use_review_evidence_v1(**arguments(data))
    descriptor = data["use_inputs"]["donor_evidence_inputs"]["parent_inputs"]["replay_inputs"][
        "parent_text_views_inputs"]["parent_descriptor"]
    path = Path(descriptor["local_path"])
    path.write_bytes(path.read_bytes() + b"\nchanged isolated plaintext review fixture")
    with pytest.raises(ValueError):
        owner.validate_parent_definition_use_review_evidence_v1(prep, **arguments(data))


@pytest.mark.parametrize("old_domain", ["official_combined", "parent_endpoint"])
@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_signed_official_or_endpoint_domain_cannot_authorize_parent_combination(
        fixtures, signed, old_domain, field):
    old = owner if old_domain == "official_combined" else endpoint_review
    prefix = "" if old_domain == "official_combined" else "PARENT_"
    name = {"schema": "CLAIM_SCHEMA", "action": "ACTION", "audience": "AUDIENCE"}[field]
    foreign = getattr(old, prefix + name)
    assert signed["reviews"][0][field] != foreign
    signed["reviews"][0][field] = foreign
    fixtures.signing.refresh(signed)
    with pytest.raises(ValueError):
        assess(fixtures, signed)


@pytest.mark.parametrize("damage", ["artifact", "owner_pin"])
def test_signed_parent_combination_still_requires_current_complete_dependencies(fixtures, signed, damage):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    fixtures.signing.refresh(signed)
    if damage == "artifact":
        identity = signed["preparation"]["required_dependency_ids"][-1]
        signed["observed_artifact_sha256s"][identity] = "0" * 64
    else:
        kind, pin = next((kind, pin) for artifact in signed["manifest"]["artifacts"]
            for kind, pins in artifact["dependency_pins"].items() for pin in pins)
        signed["observed_pins"][kind][pin["key"]] = "0" * 64
    result = assess(fixtures, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "required_dependency_closure_not_current" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert result["accepted_view_eligible"] is False


def test_parent_subject_requires_full_ordered_dependency_closure(base_materialized):
    data = base_materialized
    required = list(data["preparation"]["required_dependency_ids"])
    required.pop()
    with pytest.raises(ValueError):
        owner.build_parent_definition_use_review_subject_v1(data["preparation"], data["manifest"],
            **data["arguments"], expected_manifest_sha256=data["manifest"]["manifest_sha256"],
            required_dependency_ids=required)


def test_complete_signed_context_declaration_cannot_omit_a_parent_obligation(fixtures, signed):
    signed["reviews"][0]["context_closure"]["obligations"].pop()
    fixtures.signing.refresh(signed)
    result = assess(fixtures, signed)
    assert result["authenticated_evidence_count"] == 2
    assert "authenticated_complete_context_declarations_missing" in result["blockers"]
    assert result["context_closure_verified"] is False
    assert result["accepted_view_eligible"] is False


@pytest.mark.parametrize("damage", ["component_oversize", "aggregate_budget"])
def test_parent_review_bounds_precede_authentication_and_original_replay(case, damage, monkeypatch):
    if damage == "component_oversize":
        case["component_raw"] = b" " * (contracts.MAX_RECORD_BYTES + 1)
        case["expected_component_pin"]["component_sha256"] = sha(case["component_raw"])
    else:
        monkeypatch.setattr(owner, "MAX_INPUT_BYTES", 1)
    def no_dispatch(*args, **kwargs):
        pytest.fail("bounded review preflight must refuse before operation dispatch")
    monkeypatch.setattr(owner, "_owners", no_dispatch)
    monkeypatch.setattr(use, "_owners", no_dispatch)
    monkeypatch.setattr(parents, "validate_parent_occurrence_corpus", no_dispatch)
    with pytest.raises(ValueError):
        owner.prepare_parent_definition_use_review_evidence_v1(**arguments(case))
