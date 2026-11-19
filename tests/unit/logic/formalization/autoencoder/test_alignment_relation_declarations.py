"""Closed diagnostic relation metadata never authorizes contrastive labels."""
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lane
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_relation_declarations as subject,
)


def seal(value):
    value["content_sha256"] = subject._digest({key: item for key, item in value.items() if key != "content_sha256"})
    return value


def role(schema, **fields):
    return seal({"schema": schema, **fields})


def pins(declaration):
    return subject.stages._bindings({key: value for key, value in declaration.items()
                                     if key not in {"schema", "content_sha256"}})


def declaration(n=3, same_formal=False, unavailable=()):
    profile = role(lane.PROFILE_SCHEMA, lane_id="legacy8", stage="historical_linguistic_features", dimension=8,
        producer={"profile_id": "relation-fixture-only", "model_id": "no-model-fixture", "model_revision": "fixture-v1",
                  "code_sha256": "a" * 64, "model_assets_sha256": "b" * 64, "checkpoint_sha256": None},
        pooling={"method": "none", "endpoint": "linguistic_features"}, normalization={"kind": "none", "unit_tolerance": None},
        precision="decimal6", fit_input_recipe="exact_source_only/v1", inference_input_recipe="exact_source_only/v1")
    rows, bound, inputs = [], [], []
    for index in range(n):
        identity, text = "train_" + str(index), "Independent source statement " + str(index)
        request = {"source_text": text, "context": {"role": "none_required", "text": "", "bindings": {},
                   "sha256": hashlib.sha256(b"").hexdigest()}}
        vector = [float(index + 1), *([0.0] * 7)]
        status, reason = "available", None
        if index in unavailable:
            status, reason, vector = "unavailable", "historical representation unavailable", None
        binding = {"id": identity, "input_sha256": subject._digest(request),
                   "encoder_text_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": status, "reason": reason,
                   "vector_sha256": subject._digest(vector) if vector is not None else None,
                   "upstream_vector_sha256": None, "token_receipt_sha256": None}
        bound.append(binding)
        inputs.append({"id": identity, "input_sha256": binding["input_sha256"]})
        rows.append({**binding, "input": request, "encoder_text": text, "vector": vector,
                     "producer_row_sha256": subject._digest(binding)})
    producer = role(lane.PRODUCER_SCHEMA, profile_sha256=subject._digest(profile), rows=bound,
                    artifact_binding={"path": "never-opened-fixture.json", "bytes": 1, "sha256": "c" * 64})
    bundle = role(lane.SCHEMA, profile=profile, producer_receipt=producer, rows=rows)
    receipt = lane.validate_lane_bundle(bundle, expected_bindings={"profile_sha256": subject._digest(profile),
        "producer_receipt_sha256": subject._digest(producer), "inputs": inputs})
    train_rows = [{"id": row["id"], "input_sha256": row["input_sha256"], "representation_sha256": row["vector_sha256"],
                   "status": row["status"], "reason": row["reason"], "split": "train",
                   "formal_view_sha256": subject._digest({"fixture_formal": 0 if same_formal and index < 2 else index}),
                   "masks": dict.fromkeys(lane.MASKS, 0)} for index, row in enumerate(bound)]
    train = role("alignment-train-manifest/v1", rows=train_rows, file_binding=None)
    policy = role(subject.POLICY_SCHEMA, mode=subject.MODE, pair_order=subject.PAIR_ORDER,
        weak_structural_policy=subject.WEAK_STRUCTURAL_POLICY, family_coercion_policy=subject.FAMILY_COERCION_POLICY,
        source_family_id="declared-family-only", target_family_id=None, source_profile_sha256=receipt["profile_sha256"],
        target_profile_sha256=None)
    pairs = [{"left_id": left["id"], "right_id": right["id"],
              "left_input_sha256": left["input_sha256"], "right_input_sha256": right["input_sha256"],
              "left_formal_view_sha256": left["formal_view_sha256"], "right_formal_view_sha256": right["formal_view_sha256"],
              "relation_status": "weak_structural_identity" if left["formal_view_sha256"] == right["formal_view_sha256"] else "unknown",
              "evidence_sha256": None, "reason": "fixture declaration; not semantic evidence",
              "positive_mask": False, "permitted_negative_mask": False} for left in train_rows for right in train_rows]
    ledger = role(subject.LEDGER_SCHEMA, rows=pairs)
    return role(subject.SCHEMA, lane_validation=receipt, train_manifest=train, relation_policy=policy, pair_ledger=ledger)


def refresh(value):
    for name in ("lane_validation", "train_manifest", "relation_policy", "pair_ledger"):
        seal(value[name])
    return seal(value)


def validate(value, expected=None):
    return subject.validate_relation_declaration(value, expected_bindings=pins(value) if expected is None else expected)


def test_complete_ledger_is_deterministic_detached_and_entirely_blocked():
    value = declaration()
    original = deepcopy(value)
    result = validate(value)
    assert result == validate(value) and value == original
    assert result["pair_count"] == 9 and result["train_row_count"] == 3
    assert result["declared_relation_counts"] == {"unknown": 6, "weak_structural_identity": 3,
                                                "declared_positive": 0, "declared_negative": 0}
    assert all(result[key] is False for key in subject.FALSE)
    assert result["eligibility"] == subject.ELIGIBILITY
    assert result["masks"] == dict.fromkeys(lane.MASKS, 0)
    assert result["positive_mask"] == result["permitted_negative_mask"] == [[False] * 3 for _ in range(3)]
    assert all(row["positive_mask"] is row["permitted_negative_mask"] is False for row in result["rows"])
    assert result["weak_diagnostic_policy_required"] is True
    assert result["content_sha256"] == subject._digest({key: item for key, item in result.items() if key != "content_sha256"})
    result["rows"][0]["reason"] = "changed output"
    result["positive_mask"][0][0] = True
    assert value == original and validate(value)["positive_mask"][0][0] is False


def test_sixteen_distinct_train_formal_views_have_256_pairs_unknown240_weak16():
    result = validate(declaration(16))
    assert result["pair_count"] == 256
    assert result["declared_relation_counts"]["unknown"] == 240
    assert result["declared_relation_counts"]["weak_structural_identity"] == 16
    assert result["exact_formal_identity_pair_count"] == 16
    assert result["admitted_positive_pair_count"] == result["permitted_negative_pair_count"] == 0


def test_equal_formal_views_across_distinct_sources_remain_weak_only():
    value = declaration(same_formal=True)
    result = validate(value)
    assert result["exact_formal_identity_pair_count"] == result["declared_relation_counts"]["weak_structural_identity"] == 5
    assert result["semantic_positive_pair_count"] == 0
    assert all(not cell for row in result["positive_mask"] for cell in row)


def test_declared_relations_evidence_and_cross_family_scope_never_enable_masks():
    value = declaration()
    pairs = value["pair_ledger"]["rows"]
    pairs[1].update(relation_status="declared_positive", evidence_sha256="d" * 64)
    pairs[3].update(relation_status="declared_negative", evidence_sha256="e" * 64)
    value["relation_policy"].update(target_family_id="another-declared-family", target_profile_sha256="f" * 64)
    result = validate(refresh(value))
    assert result["declared_relation_counts"]["declared_positive"] == result["declared_relation_counts"]["declared_negative"] == 1
    assert result["declared_evidence_count"] == 2 and result["admitted_evidence_count"] == 0
    assert result["rows"][1]["evidence_status"] == "declared_unverified_unadmitted"
    assert result["declared_family_profile_scope"]["target_profile_sha256"] == "f" * 64
    assert result["family_profile_scope_verified"] is result["evidence_contents_verified"] is False
    assert all(not cell for row in result["permitted_negative_mask"] for cell in row)


def test_even_contradictory_declarations_are_metadata_and_identity_does_not_auto_admit():
    value = declaration()
    value["pair_ledger"]["rows"][0]["relation_status"] = "declared_negative"
    result = validate(refresh(value))
    assert result["declared_relation_counts"]["declared_negative"] == 1
    assert result["exact_formal_identity_pair_count"] == 3
    assert result["permitted_negative_pair_count"] == 0


def test_missing_representation_is_retained_not_dropped_from_cartesian_ledger():
    result = validate(declaration(unavailable=(1,)))
    assert result["train_row_count"] == 3 and result["pair_count"] == 9
    assert result["eligibility"] == subject.ELIGIBILITY


@pytest.mark.parametrize("field", ["left_id", "right_id", "left_input_sha256", "right_input_sha256",
                                   "left_formal_view_sha256", "right_formal_view_sha256"])
def test_resealed_pair_foreign_join_rejects_even_when_its_role_is_repinned(field):
    value = declaration()
    value["pair_ledger"]["rows"][1][field] = "foreign" if field.endswith("_id") else "f" * 64
    with pytest.raises(ValueError, match="binding differs"):
        validate(refresh(value))


@pytest.mark.parametrize("operation", ["reorder", "missing", "duplicate", "extra"])
def test_pair_ledger_is_complete_exactly_once_and_in_train_row_major_order(operation):
    value = declaration()
    pairs = value["pair_ledger"]["rows"]
    if operation == "reorder":
        pairs[1], pairs[3] = pairs[3], pairs[1]
    elif operation == "missing":
        pairs.pop()
    elif operation == "duplicate":
        pairs[1] = deepcopy(pairs[0])
    else:
        pairs.append(deepcopy(pairs[0]))
    with pytest.raises(ValueError):
        validate(refresh(value))


def test_weak_identity_cannot_be_claimed_for_different_formal_hashes():
    value = declaration()
    value["pair_ledger"]["rows"][1]["relation_status"] = "weak_structural_identity"
    with pytest.raises(ValueError, match="exact formal-view identity"):
        validate(refresh(value))


@pytest.mark.parametrize("field,value", [("positive_mask", True), ("positive_mask", 0),
                                        ("permitted_negative_mask", True), ("permitted_negative_mask", 0)])
def test_declared_pair_masks_are_exact_false_not_bool_integer_aliases(field, value):
    item = declaration()
    item["pair_ledger"]["rows"][1][field] = value
    with pytest.raises(ValueError, match="exact boolean false"):
        validate(refresh(item))


@pytest.mark.parametrize("location", ["declaration", "policy", "ledger", "pair", "train"])
def test_authority_or_review_fields_are_closed_not_implicitly_admitted(location):
    value = declaration()
    targets = {"declaration": value, "policy": value["relation_policy"], "ledger": value["pair_ledger"],
               "pair": value["pair_ledger"]["rows"][0], "train": value["train_manifest"]}
    targets[location]["semantic_label_admission"] = True
    with pytest.raises(ValueError, match="closed"):
        validate(refresh(value))


@pytest.mark.parametrize("name", ["lane_validation", "train_manifest", "relation_policy", "pair_ledger"])
def test_local_resealing_cannot_replace_an_externally_selected_role(name):
    value = declaration()
    expected = pins(value)
    if name == "lane_validation":
        value[name]["bundle_sha256"] = "f" * 64
    elif name == "train_manifest":
        value[name]["rows"][0]["formal_view_sha256"] = "f" * 64
    elif name == "relation_policy":
        value[name]["target_family_id"] = "new-family-declaration"
    else:
        value[name]["rows"][0]["reason"] = "new evidence declaration"
    with pytest.raises(ValueError, match="externally pinned"):
        validate(refresh(value), expected)


def test_external_pins_include_ordered_pair_rows_digest_and_full_sealed_value():
    value = declaration()
    expected = pins(value)
    expected["pair_ledger"]["rows_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="ordered rows"):
        validate(value, expected)
    expected = pins(value)
    expected["pair_ledger"]["value_sha256"] = subject._digest(value["pair_ledger"]["rows"])
    with pytest.raises(ValueError, match="externally pinned"):
        validate(value, expected)


def test_required_external_roles_and_their_separate_byte_bound_are_enforced():
    value = declaration()
    expected = pins(value)
    expected.pop("pair_ledger")
    with pytest.raises(ValueError, match="closed"):
        validate(value, expected)
    expected = pins(value)
    expected["extra"] = "x" * (subject.MAX_EXPECTED_BYTES + 1)
    with pytest.raises(ValueError, match="external relation pins byte bound"):
        validate(value, expected)


def test_train_source_profile_input_and_vector_receipt_joins_are_independent():
    for key in ("input_sha256", "representation_sha256"):
        value = declaration()
        value["train_manifest"]["rows"][0][key] = "f" * 64
        with pytest.raises(ValueError, match="ordered ledger differs"):
            validate(refresh(value))
    value = declaration()
    value["relation_policy"]["source_profile_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source profile differs"):
        validate(refresh(value))


@pytest.mark.parametrize("field,value", [("split", "validation"), ("masks", dict.fromkeys(lane.MASKS, 1)),
                                        ("masks", dict.fromkeys(lane.MASKS, False))])
def test_only_train_and_exact_integer_zero_supervision_masks_are_accepted(field, value):
    item = declaration()
    item["train_manifest"]["rows"][0][field] = value
    with pytest.raises(ValueError):
        validate(refresh(item))


@pytest.mark.parametrize("field,value", [("mode", "train_now"), ("pair_order", "unordered"),
                                        ("weak_structural_policy", "semantic_equivalence"),
                                        ("family_coercion_policy", "coerce_all_families")])
def test_policy_cannot_enable_fitting_coercion_or_implicit_relations(field, value):
    item = declaration()
    item["relation_policy"][field] = value
    with pytest.raises(ValueError, match="differs"):
        validate(refresh(item))


@pytest.mark.parametrize("field,value", [("evidence_sha256", "not-a-sha"), ("reason", ""),
                                        ("reason", "x" * 4097), ("relation_status", "admitted_positive")])
def test_pair_metadata_is_bounded_closed_and_not_an_admission_receipt(field, value):
    item = declaration()
    item["pair_ledger"]["rows"][0][field] = value
    with pytest.raises(ValueError):
        validate(refresh(item))


def test_empty_oversized_nonfinite_and_nonordinary_json_fail_closed():
    value = declaration()
    value["train_manifest"]["rows"] = []
    with pytest.raises(ValueError):
        validate(refresh(value))
    with pytest.raises(ValueError):
        validate(declaration(0))
    with pytest.raises(ValueError):
        validate(declaration(129))
    value = declaration()
    value["pair_ledger"]["rows"][0]["reason"] = float("nan")
    with pytest.raises(ValueError):
        subject.validate_relation_declaration(value, expected_bindings={})
    value["pair_ledger"]["rows"][0]["reason"] = object()
    with pytest.raises(ValueError):
        subject.validate_relation_declaration(value, expected_bindings={})
    value = declaration()
    value["extra"] = "x" * (subject.MAX_BYTES + 1)
    with pytest.raises(ValueError, match="byte bound"):
        subject.validate_relation_declaration(value, expected_bindings={})


def test_no_file_model_or_prover_access_during_validation_and_no_optional_imports(tmp_path):
    root = Path(__file__).resolve().parents[5]
    value = declaration()
    payload = json.dumps({"declaration": value, "expected": pins(value)})
    code = '''
import importlib.abc,json,sys,types
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root))
for name,relative in [('ipfs_datasets_py','ipfs_datasets_py'),('ipfs_datasets_py.logic','ipfs_datasets_py/logic'),('ipfs_datasets_py.logic.formalization','ipfs_datasets_py/logic/formalization'),('ipfs_datasets_py.logic.formalization.autoencoder','ipfs_datasets_py/logic/formalization/autoencoder')]:
 m=types.ModuleType(name);m.__path__=[str(root/relative)];m.__package__=name;sys.modules[name]=m
blocked={'torch','numpy','scipy','transformers','sentence_transformers','spacy','safetensors','tensorflow','jax','lean','z3','cvc5'}
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in blocked: raise RuntimeError('optional stack import')
sys.meta_path.insert(0,Guard())
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_relation_declarations import validate_relation_declaration
request=json.loads(sys.stdin.read())
def deny(event,args):
 if event in {'open','os.listdir','os.scandir','subprocess.Popen','socket.__new__'}: raise RuntimeError('I/O during relation validation')
sys.addaudithook(deny)
result=validate_relation_declaration(request['declaration'],expected_bindings=request['expected'])
assert result['eligibility']=='blocked_no_admitted_relations'
assert not blocked.intersection(sys.modules)
print(json.dumps({'pair_count':result['pair_count'],'calls':result['model_calls']+result['prover_calls']}))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)], input=payload,
                            text=True, capture_output=True, cwd=tmp_path, timeout=10, check=True)
    assert json.loads(result.stdout) == {"pair_count": 9, "calls": 0}


# The V2 miniature Act, vector declarations, registries and review process are
# fictional engineering controls. No actual encoder execution is asserted.
def _reviewed_pair_fixture(*, norm_fixture_options=None, lineage_group_id="fixture:reviewed-act-lineage",
        sample_id_prefix="sample:", ledger_id="fixture:reviewed-pairs", admission_version="v2", include_definition=False,
        reviewed_norm_case=None, shared_split_manifest=None, sample_ids_by_unit=None):
    import importlib.util
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    from ipfs_datasets_py.logic.autoformal import legal_graph_review as auth
    from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    helper_path = Path(__file__).resolve().parents[2] / "autoformal" / "test_legal_norm_content_adjudication_v1.py"
    spec = importlib.util.spec_from_file_location("_reviewed_pairs_norm_fixture", helper_path)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if reviewed_norm_case is None:
        assert shared_split_manifest is None and sample_ids_by_unit is None
        norm_case = helper.reviewed_norm_fixture_v2(admission,
            **({} if norm_fixture_options is None else norm_fixture_options))
        assert admission_version in {"v2", "v3"}
        if admission_version == "v3":
            from tests.unit.logic.autoformal import test_legal_reviewed_norm_admission_v3 as mixed
            from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as admission
            norm_case["declaration"]["schema"] = admission.REVIEWED_DECLARATION_SCHEMA
            for unit in norm_case["declaration"]["units"]:
                unit["relational_profile"] = mixed.relational.PROFILE
            mixed.set_mixed_ir(norm_case)
            norm_case["preparation"] = mixed.prepare(admission, norm_case)
            mixed.refresh_signed_reviews(norm_case, admission)
    else:
        # Reuse the complete independent fictional TRAIN review without
        # regenerating, transforming or resigning its meaning/interpretation.
        assert admission_version == "v3" and include_definition is True
        assert norm_fixture_options is None and type(shared_split_manifest) is dict
        assert type(sample_ids_by_unit) is dict
        from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as admission
        norm_case = helper.clone_source(reviewed_norm_case)
        assert norm_case["declaration"]["schema"] == admission.REVIEWED_DECLARATION_SCHEMA
    args, kwargs = helper.reviewed_assessment_arguments_v2(admission, norm_case)
    assess = (admission.assess_reviewed_norm_admission_v3 if admission_version == "v3"
              else admission.assess_reviewed_norm_admission_v2)
    norm_report = assess(*args, **kwargs)
    assert norm_report["semantic_use_eligible"] is True
    suffix = admission_version
    pair_domain = {"REVIEWED_BODY_SCHEMA": "alignment-reviewed-pair-declaration/" + suffix,
        "REVIEWED_ACTION": "authorize_reviewed_contrastive_pair_labels/" + suffix,
        "REVIEWED_AUDIENCE": "legal-autoformalization-reviewed-contrastive-pairs/" + suffix,
        "REVIEWED_CLAIM_SCHEMA": "alignment-reviewed-pair-signed-claim/" + suffix}

    assert type(include_definition) is bool
    admitted = norm_report["units"] if include_definition else norm_report["units"][1:]
    unit_indices = {unit["unit_id"]: index for index, unit in enumerate(admitted)}
    profile = role(lane.PROFILE_SCHEMA, lane_id="native384", stage="raw_embedding", dimension=384,
        producer={"profile_id": "fixture:gte-compatible-native384", "model_id": "fixture:no-actual-encoder-run",
            "model_revision": "fixture:revision-1", "code_sha256": "a" * 64,
            "model_assets_sha256": "b" * 64, "checkpoint_sha256": None},
        pooling={"method": "mean", "endpoint": "fixture:encoder-output"},
        normalization={"kind": "l2", "unit_tolerance": 0.001}, precision="float32",
        fit_input_recipe="exact_source_only/v1", inference_input_recipe="exact_source_only/v1")

    def producer_lane(side, selected):
        rows, bound, inputs = [], [], []
        for ordinal, unit in enumerate(selected):
            identity = side + ":" + str(ordinal)
            text = unit["source_text"] if side == "source" else admission.norm._wire(unit["canonical_ir"]).decode("utf-8")
            request = {"source_text": text, "context": {"role": "none_required", "text": "", "bindings": {},
                "sha256": hashlib.sha256(b"").hexdigest()}}
            vector = [0.0] * 384
            vector[unit_indices[unit["unit_id"]]] = 1.0
            binding = {"id": identity, "input_sha256": lane._digest(request),
                "encoder_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "status": "available", "reason": None,
                "vector_sha256": lane._digest(vector), "upstream_vector_sha256": None, "token_receipt_sha256": None}
            rows.append({**binding, "input": request, "encoder_text": text, "vector": vector,
                "producer_row_sha256": lane._digest(binding)})
            bound.append(binding)
            inputs.append({"id": identity, "input_sha256": binding["input_sha256"]})
        producer = role(lane.PRODUCER_SCHEMA, profile_sha256=lane._digest(profile), rows=bound,
            artifact_binding={"path": "never-opened-fictional-vector-declarations.json", "bytes": 1, "sha256": "c" * 64})
        bundle = role(lane.SCHEMA, profile=deepcopy(profile), producer_receipt=producer, rows=rows)
        expected = {"profile_sha256": lane._digest(profile), "producer_receipt_sha256": lane._digest(producer), "inputs": inputs}
        return bundle, expected

    source_lane, source_bindings = producer_lane("source", admitted)
    formal_units = [admitted[0], admitted[0], *admitted[1:]]
    formal_lane, formal_bindings = producer_lane("formal", formal_units)
    if shared_split_manifest is None:
        examples = [splits.LegalIRSplitExample.from_sample({"sample_id": sample_id_prefix + str(index),
            "source_text": unit["source_text"], "lineage_group_id": lineage_group_id})
            for index, unit in enumerate(admitted)]
        split_manifest = splits.LegalIRSplitManifest(examples=tuple(examples),
            assignments={example.sample_id: "train" for example in examples}, config_digest="d" * 64,
            metadata={"fixture_only": True}).to_dict()
    else:
        split_manifest = deepcopy(shared_split_manifest)
        manifest = splits.LegalIRSplitManifest.from_mapping(split_manifest)
        indexed = {example.sample_id:example for example in manifest.examples}
        assert set(sample_ids_by_unit) == {unit["unit_id"] for unit in admitted}
        assert len(set(sample_ids_by_unit.values())) == len(admitted)
        examples = [indexed[sample_ids_by_unit[unit["unit_id"]]] for unit in admitted]
        assert all(manifest.assignments[example.sample_id] == "train" for example in examples)
        assert all(example.content_hash == splits._content_hash(unit["source_text"])
                   for example,unit in zip(examples,admitted,strict=True))
    admission_id = "fixture:norm-admission"
    group_sha = lane._digest(norm_case["manifest"]["expected_artifact_ids"])
    def endpoints(side, selected, bundle):
        result = []
        for unit, row in zip(selected, bundle["rows"]):
            ir = unit["canonical_ir"]
            scope = {key: ir[key] for key in ("governing_context", "interpretation_id", "assumptions")}
            sample_index = unit_indices[unit["unit_id"]]
            result.append({"id": row["id"], "unit_id": unit["unit_id"], "admission_id": admission_id,
                "source_sha256": hashlib.sha256(unit["source_text"].encode("utf-8")).hexdigest(),
                "formal_view_sha256": admission.norm_content_adjudication_sha256(ir),
                "context_sha256": admission.norm_content_adjudication_sha256(scope), "input_sha256": row["input_sha256"],
                "vector_sha256": row["vector_sha256"], "split_sample_id": examples[sample_index].sample_id,
                "exposure_group": examples[sample_index].lineage_group_id, "dependency_group_sha256": group_sha})
        return result
    source_endpoints = endpoints("source", admitted, source_lane)
    formal_endpoints = endpoints("formal", formal_units, formal_lane)
    process_id = "fixture:pair-process-evidence"
    process_raw = b"Fictional independent whole-ledger pair/purpose review process; no actual law or producer execution."
    process_ref = {"artifact_id": process_id, "sha256": hashlib.sha256(process_raw).hexdigest()}
    pair_relations = ["corresponding", "equivalent", "incompatible", "unknown", "analogy", "corresponding"]
    pairs = [{"left_id": source["id"], "right_id": formal["id"], "relation": (pair_relations[i * 3 + j] if not include_definition else
            "equivalent" if i == 0 and j == 1 else "corresponding" if source["unit_id"] == formal["unit_id"]
            else ("incompatible", "unknown", "analogy")[(i + j) % 3]),
        "reason": "Explicit fictional directed-pair declaration; unknown and analogy are excluded.",
        "evidence_refs": [] if (pair_relations[i * 3 + j] if not include_definition else
            "equivalent" if i == 0 and j == 1 else "corresponding" if source["unit_id"] == formal["unit_id"]
            else ("incompatible", "unknown", "analogy")[(i + j) % 3]) in ("unknown", "analogy") else [deepcopy(process_ref)]}
        for i, source in enumerate(source_endpoints) for j, formal in enumerate(formal_endpoints)]
    author = Ed25519Signer.generate("did:example:fictional-pair-ledger-author")
    body = {"schema": pair_domain["REVIEWED_BODY_SCHEMA"], "ledger_id": ledger_id,
        "purpose": "contrastive_supervision", "provenance_kind": "fictional_fixture", "declared_at_utc": helper.EVALUATED,
        "source_endpoints": source_endpoints, "formal_endpoints": formal_endpoints, "pairs": pairs,
        "author_actors": [{"principal_id": "fixture:pair-ledger-author", "signer_did": author.did,
            "public_key_hex": author.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()}],
        "source_lane_sha256": lane._digest(source_lane), "formal_lane_sha256": lane._digest(formal_lane),
        "split_manifest_sha256": lane._digest(split_manifest)}
    endpoint_admissions = {admission_id: {"report": norm_report, "args": list(args), "kwargs": kwargs,
        "expected_report_sha256": admission.norm_content_adjudication_sha256(norm_report)}}
    preparation_inputs = {"body": body, "expected_body_sha256": admission.norm_content_adjudication_sha256(body),
        "endpoint_admissions": endpoint_admissions, "source_lane": source_lane, "formal_lane": formal_lane,
        "expected_source_lane_bindings": source_bindings, "expected_formal_lane_bindings": formal_bindings,
        "split_manifest": split_manifest, "expected_split_manifest_sha256": lane._digest(split_manifest),
        "allow_fictional_fixture": True}
    artifact_pins = {body["ledger_id"]: preparation_inputs["expected_body_sha256"],
        body["ledger_id"] + ":admission:" + admission_id: endpoint_admissions[admission_id]["expected_report_sha256"],
        body["ledger_id"] + ":source-lane": lane._digest(source_lane),
        body["ledger_id"] + ":formal-lane": lane._digest(formal_lane),
        body["ledger_id"] + ":split": lane._digest(split_manifest)}
    artifacts = [{"artifact_id": key, "artifact_sha256": digest,
        "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS}} for key, digest in artifact_pins.items()]
    dependency_manifest = dependencies.build_dependency_manifest(artifacts,
        [{"dependent_id": body["ledger_id"], "dependency_id": key} for key in artifact_pins if key != body["ledger_id"]],
        expected_artifact_ids=list(artifact_pins))
    preparation_inputs.update(dependency_manifest=dependency_manifest,
        expected_manifest_sha256=dependency_manifest["manifest_sha256"])
    prepare_pair = (subject.prepare_reviewed_relation_declaration_v3 if admission_version == "v3"
                    else subject.prepare_reviewed_relation_declaration_v2)
    preparation = prepare_pair(**preparation_inputs)
    signing_subject = preparation["subject"]
    signers = [Ed25519Signer.generate("did:example:fictional-pair-" + role) for role in auth.ROLES]
    keys = [{"key_id": "fixture:pair-key:" + str(i), "signer_did": signer.did,
        "public_key_hex": signer.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(),
        "principal_id": "fixture:pair-reviewer:" + str(i), "roles": [role], "scope_ids": [signing_subject["scope_id"]],
        "valid_from_utc": helper.REVIEWED_START, "valid_until_utc": helper.REVIEWED_END, "revoked_at_utc": None}
        for i, (signer, role) in enumerate(zip(signers, auth.ROLES))]
    registry = {"schema": auth.REGISTRY_SCHEMA, "mode": "external_pinned_trust", "process_id": "fixture:pair-review-process",
        "generation": 1, "revocation_generation": 0, "valid_from_utc": helper.REVIEWED_START,
        "valid_until_utc": helper.REVIEWED_END, "keys": keys, "revoked_principals": []}
    policy = {"schema": auth.POLICY_SCHEMA, "mode": registry["mode"], "policy_id": "fixture:pair-policy",
        "process_id": registry["process_id"], "registry_sha256": auth.digest(registry),
        "action": pair_domain["REVIEWED_ACTION"], "audience": pair_domain["REVIEWED_AUDIENCE"], "required_roles": list(auth.ROLES),
        "valid_from_utc": helper.REVIEWED_START, "valid_until_utc": helper.REVIEWED_END, "max_review_age_seconds": 86400}
    body_raw = admission.norm._wire(body)
    body_ref = {"artifact_id": body["ledger_id"], "sha256": hashlib.sha256(body_raw).hexdigest()}
    closure = {"status": "declared_complete", "obligations": [{"slot_id": slot,
        "disposition": "resolved_by_evidence", "evidence_refs": [deepcopy(body_ref), deepcopy(process_ref)]}
        for slot in subject.REVIEWED_SLOTS], "unresolved": []}
    reviews = [signer.sign({"schema": pair_domain["REVIEWED_CLAIM_SCHEMA"], "action": pair_domain["REVIEWED_ACTION"],
        "audience": pair_domain["REVIEWED_AUDIENCE"], "review_id": "fixture:pair-review:" + str(i),
        "key_id": keys[i]["key_id"], "principal_id": keys[i]["principal_id"], "role": role,
        "registry_sha256": auth.digest(registry), "policy_sha256": auth.digest(policy),
        "issued_at_utc": helper.EVALUATED, "expires_at_utc": helper.EXPIRES, "subject": deepcopy(signing_subject),
        "interpretation": {"decision": "support", "reviewed_graph_sha256": signing_subject["graph_sha256"],
            "reviewed_ast_sha256": signing_subject["ast_sha256"], "rationale": "Fictional full pair/purpose review only.",
            "ambiguity": []}, "context_closure": deepcopy(closure)})
        for i, (signer, role) in enumerate(zip(signers, auth.ROLES))]
    return {"preparation_inputs": preparation_inputs, "preparation": preparation, "registry": registry,
        "policy": policy, "reviews": reviews, "signers": signers, "at_time_utc": helper.EVALUATED,
        "evidence": {body["ledger_id"]: body_raw, process_id: process_raw},
        "observed_artifacts": artifact_pins, "observed_pins": {kind: {} for kind in dependencies.PIN_KINDS},
        "current_endpoint_observations": {admission_id: {
            "observed_artifact_sha256s": deepcopy(kwargs["observed_artifact_sha256s"]),
            "observed_pins": deepcopy(kwargs["observed_pins"])}}}


def reviewed_pair_fixture_v2(**options):
    return _reviewed_pair_fixture(**options, admission_version="v2")


def reviewed_pair_fixture_v3(**options):
    return _reviewed_pair_fixture(**options, admission_version="v3")


@pytest.fixture(scope="module")
def reviewed_pairs_v2():
    return reviewed_pair_fixture_v2()


def test_reviewed_pair_preparation_replays_endpoints_and_preserves_rectangular_unknowns(reviewed_pairs_v2):
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    case = reviewed_pairs_v2
    prepared = case["preparation"]
    assert subject.validate_reviewed_relation_declaration_v2(prepared,
        expected_preparation_sha256=admission.norm_content_adjudication_sha256(prepared),
        **case["preparation_inputs"]) == prepared
    assert len(prepared["source_endpoints"]) == 2 and len(prepared["formal_endpoints"]) == 3
    assert len(prepared["pairs"]) == 6
    assert [row["relation"] for row in prepared["pairs"]] == [
        "corresponding", "equivalent", "incompatible", "unknown", "analogy", "corresponding"]
    assert prepared["semantic_label_admission"] is False
    assert prepared["runtime_computation_proven"] is prepared["actual_fit_authorized"] is False
    assert all(len(vector) == 384 for vector in prepared["source_vectors"] + prepared["formal_vectors"])


@pytest.mark.parametrize("damage", ["source", "typed_ir", "endpoint_admission", "purpose", "context", "view", "vector",
    "vector_order", "split", "dependency_group", "unknown_pair", "fixture_opt_in"])
def test_reviewed_pair_preparation_refuses_changed_endpoint_purpose_context_vectors_and_splits(reviewed_pairs_v2, damage):
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    inputs = deepcopy(reviewed_pairs_v2["preparation_inputs"])
    entry = next(iter(inputs["endpoint_admissions"].values()))
    if damage == "source":
        source = entry["kwargs"]["preparation_inputs"]["source_inputs"]
        source[next(iter(source))]["raw_bytes"] += b" changed"
    elif damage == "typed_ir":
        irs = entry["kwargs"]["preparation_inputs"]["relational_inputs"]
        irs[next(iter(irs))]["report"]["typed_expression"] = {}
    elif damage == "endpoint_admission": entry["report"]["semantic_use_eligible"] = False
    elif damage == "purpose": inputs["body"]["purpose"] = "retrieve_only"
    elif damage == "context": inputs["body"]["source_endpoints"][0]["context_sha256"] = "e" * 64
    elif damage == "view": inputs["body"]["formal_endpoints"][0]["formal_view_sha256"] = "e" * 64
    elif damage == "vector": inputs["formal_lane"]["rows"][0]["vector"][0] = 0.5
    elif damage == "vector_order": inputs["formal_lane"]["rows"].reverse()
    elif damage == "split": inputs["split_manifest"]["assignments"][next(iter(inputs["split_manifest"]["assignments"]))] = "holdout"
    elif damage == "dependency_group": inputs["body"]["source_endpoints"][0]["dependency_group_sha256"] = "e" * 64
    elif damage == "unknown_pair": inputs["body"]["pairs"][3]["relation"] = "automatic_negative"
    elif damage == "fixture_opt_in": inputs["allow_fictional_fixture"] = False
    inputs["expected_body_sha256"] = admission.norm_content_adjudication_sha256(inputs["body"])
    with pytest.raises(ValueError):
        subject.prepare_reviewed_relation_declaration_v2(**inputs)


@pytest.mark.parametrize("target_kind", ["self", "stage", "lane"])
def test_reviewed_relation_raw_sources_are_pinned_at_import_before_first_v2_call(monkeypatch, target_kind):
    paths = {"self": subject.__file__, "stage": subject.stages.__file__, "lane": subject._reviewed_lane_owner.__file__}
    target = str(Path(paths[target_kind]).resolve())
    assert target in subject._REVIEWED_IMPORTED_RAW_PINS
    original_read = Path.read_bytes
    def changed_read(path):
        raw = original_read(path)
        return raw + b"\n# mocked direct-source drift\n" if str(path.resolve()) == target else raw
    monkeypatch.setattr(Path, "read_bytes", changed_read)
    with pytest.raises(ValueError, match="changed since import"):
        subject._reviewed_pins()



def declared_composed_reviewed_pair_fixture_v3(tmp_path, *, refresh=True):
    """Fictional externally declared vectors; no encoder execution/quality claim."""
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as masks
    from tests.unit.logic.formalization.autoencoder import test_alignment_richer_embeddings as numeric
    fixtures,plan,receipt,options=numeric._declared_complete_composition_case(tmp_path)
    composition=numeric.subject.compose_native384_complete_chunks(plan,receipt,**options)
    case=reviewed_pair_fixture_v3()
    inputs=case['preparation_inputs'];body=inputs['body']
    for side in ('source','formal'):
        bundle=inputs[side+'_lane'];bundle['profile']=deepcopy(composition['profile'])
        for row in bundle['rows']:
            # Declared numerical DATA is deliberately independent of the above
            # profile fixture. Complete-vector inference is tested elsewhere.
            row['upstream_vector_sha256']=lane._digest({'declared_mean':row['vector']})
            row['token_receipt_sha256']=lane._digest({'declared_chunks':row['id']})
            binding={key:row[key] for key in lane.ROW_BINDING_FIELDS}
            row['producer_row_sha256']=lane._digest(binding)
        producer=bundle['producer_receipt'];producer['profile_sha256']=lane._digest(bundle['profile'])
        producer['rows']=[{key:row[key] for key in lane.ROW_BINDING_FIELDS} for row in bundle['rows']]
        seal(producer);seal(bundle)
        expected=inputs['expected_'+side+'_lane_bindings'];expected['profile_sha256']=lane._digest(bundle['profile']);expected['producer_receipt_sha256']=lane._digest(producer)
        body[side+'_lane_sha256']=lane._digest(bundle)
        artifact_id=body['ledger_id']+':'+side+'-lane'
        next(row for row in inputs['dependency_manifest']['artifacts'] if row['artifact_id']==artifact_id)['artifact_sha256']=lane._digest(bundle)
        case['observed_artifacts'][artifact_id]=lane._digest(bundle)
    inputs['representation_stage']='complete_chunk_composition'
    if refresh:masks.refresh_reviewed_pair_ledger_v3(case)
    return case


@pytest.mark.parametrize('damage',[None,'no-opt-in','unknown-stage','raw-downgrade','mixed-profile'])
def test_reviewed_v3_composed_profile_requires_explicit_exact_opt_in(tmp_path,damage):
    case=declared_composed_reviewed_pair_fixture_v3(tmp_path)
    inputs=deepcopy(case['preparation_inputs'])
    if damage=='no-opt-in':inputs.pop('representation_stage')
    elif damage=='unknown-stage':inputs['representation_stage']='inferred-from-vector-width'
    elif damage=='raw-downgrade':inputs['representation_stage']='raw_embedding'
    elif damage=='mixed-profile':
        inputs['formal_lane']=reviewed_pair_fixture_v3()['preparation_inputs']['formal_lane']
    if damage is not None:
        with pytest.raises(ValueError):subject.prepare_reviewed_relation_declaration_v3(**inputs)
    else:
        result=subject.prepare_reviewed_relation_declaration_v3(**inputs)
        assert result['source_representation_profile']['stage']==result['formal_representation_profile']['stage']=='complete_chunk_composition'
        assert result['semantic_label_admission'] is result['actual_fit_authorized'] is result['runtime_computation_proven'] is False
        assert result==subject.validate_reviewed_relation_declaration_v3(result,expected_preparation_sha256=lane._digest(result),**inputs)


def reviewed_pair_fixture_v4(*, fixture_factory=reviewed_pair_fixture_v3, declarations=subject, lane=lane,
        prepare=True, cross_relation="mixed"):
    """Combine two genuine *fictional* V3 admissions without rewriting either.

    New context-set label reviews are signed in the explicit V4 fixture domain.
    Existing independent pair keys may be reused under a fresh exact set-scope
    registry/policy; no global endpoint/pair reviewer-disjointness is claimed.
    All source and formal vectors remain authored declarations, not inference.
    """
    import hashlib
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
    from ipfs_datasets_py.logic.autoformal import legal_graph_review as auth
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits

    assert cross_relation in {"mixed", "unknown", "analogy", "incompatible"}
    cases = {key: fixture_factory(
        norm_fixture_options={"fixture_namespace": "v4-context-" + key,
            "governing_instrument_id": "fixture:shared-v4-governing-act"},
        lineage_group_id="fixture:v4-lineage-" + key,
        sample_id_prefix="v4:" + key + ":", ledger_id="fixture:original-v3-pairs-" + key)
        for key in ("a", "b")}
    inputs = deepcopy(cases["a"]["preparation_inputs"])
    body = inputs["body"]
    body.update(schema="alignment-reviewed-pair-declaration/v4",
        ledger_id="fixture:two-context-v4-pairs")
    body["author_actors"] = [deepcopy(actor) for case in cases.values()
        for actor in case["preparation_inputs"]["body"]["author_actors"]]
    admissions, endpoint_ids, contexts = {}, {}, {}
    for key, case in cases.items():
        admissions["fixture:v4-admission-" + key] = deepcopy(next(iter(
            case["preparation_inputs"]["endpoint_admissions"].values())))
        for endpoint in (*case["preparation"]["source_endpoints"],
                         *case["preparation"]["formal_endpoints"]):
            scope = deepcopy(endpoint["scope"])
            digest = admission.norm_content_adjudication_sha256(scope)
            assert digest == endpoint["context_sha256"]
            contexts[digest] = {"context_sha256": digest, "scope": scope}
    assert len(contexts) == 2
    ordered_contexts = [contexts[key] for key in sorted(contexts)]
    assert ordered_contexts[0]["scope"]["governing_context"] == ordered_contexts[1]["scope"]["governing_context"]
    assert ordered_contexts[0]["scope"]["assumptions"] == ordered_contexts[1]["scope"]["assumptions"]
    assert ordered_contexts[0]["scope"]["interpretation_id"] != ordered_contexts[1]["scope"]["interpretation_id"]
    body["context_set"] = ordered_contexts

    for side in ("source", "formal"):
        rows, bound_rows, endpoints = [], [], []
        for key, case in cases.items():
            previous = case["preparation_inputs"]
            endpoint_ids[key, side] = {}
            for ordinal, (row, endpoint) in enumerate(zip(previous[side + "_lane"]["rows"],
                    previous["body"][side + "_endpoints"], strict=True)):
                row, endpoint = deepcopy(row), deepcopy(endpoint)
                identity = side + ":" + key + ":" + str(ordinal)
                endpoint_ids[key, side][row["id"]] = identity
                row["id"] = identity
                bound = {name: row[name] for name in ("id", "input_sha256", "encoder_text_sha256",
                    "status", "reason", "vector_sha256", "upstream_vector_sha256", "token_receipt_sha256")}
                row["producer_row_sha256"] = lane._digest(bound)
                rows.append(row); bound_rows.append(bound)
                endpoint.update(id=identity, admission_id="fixture:v4-admission-" + key)
                endpoints.append(endpoint)
        bundle = deepcopy(inputs[side + "_lane"])
        bundle["rows"] = rows
        producer = bundle["producer_receipt"]
        producer["rows"] = bound_rows
        producer["content_sha256"] = lane._digest({k: v for k, v in producer.items() if k != "content_sha256"})
        bundle["content_sha256"] = lane._digest({k: v for k, v in bundle.items() if k != "content_sha256"})
        inputs[side + "_lane"] = bundle
        inputs["expected_" + side + "_lane_bindings"] = {
            "profile_sha256": lane._digest(bundle["profile"]),
            "producer_receipt_sha256": lane._digest(producer),
            "inputs": [{"id": row["id"], "input_sha256": row["input_sha256"]} for row in rows]}
        body[side + "_endpoints"] = endpoints
        body[side + "_lane_sha256"] = lane._digest(bundle)

    examples, assignments = [], {}
    for case in cases.values():
        manifest = splits.LegalIRSplitManifest.from_mapping(case["preparation_inputs"]["split_manifest"])
        examples.extend(manifest.examples); assignments.update(manifest.assignments)
    manifest = splits.LegalIRSplitManifest(examples=tuple(examples), assignments=assignments,
        config_digest="d" * 64, metadata={"fixture_only": True}).to_dict()
    inputs.update(endpoint_admissions=admissions, split_manifest=manifest,
        expected_split_manifest_sha256=lane._digest(manifest))
    body["split_manifest_sha256"] = lane._digest(manifest)

    # Review process evidence is newly authored for the combined V4 ledger.
    # Neither original V3 pair signatures nor endpoint closures are witnesses.
    process_id = "fixture:independent-v4-context-pair-process"
    process_raw = (b"Fictional independent V4 whole-context-set directed-pair meaning review process; "
        b"no actual law, controlling authority, applicability, proof or encoder execution.")
    process_ref = {"artifact_id": process_id, "sha256": hashlib.sha256(process_raw).hexdigest()}
    own_pairs = {}
    for key, case in cases.items():
        for pair in case["preparation_inputs"]["body"]["pairs"]:
            pair = deepcopy(pair)
            pair["left_id"] = endpoint_ids[key, "source"][pair["left_id"]]
            pair["right_id"] = endpoint_ids[key, "formal"][pair["right_id"]]
            own_pairs[pair["left_id"], pair["right_id"]] = pair
    pairs = []
    for source in body["source_endpoints"]:
        for formal in body["formal_endpoints"]:
            old = own_pairs.get((source["id"], formal["id"]))
            relation = old["relation"] if old else cross_relation
            if relation == "mixed":
                relation = ("incompatible" if (source["id"], formal["id"]) == ("source:a:0", "formal:b:2")
                    else "analogy" if (source["id"], formal["id"]) == ("source:b:1", "formal:a:0") else "unknown")
            pairs.append({"left_id": source["id"], "right_id": formal["id"], "relation": relation,
                "reason": "Explicit fictional context-bound meaning label; no legal applicability inferred.",
                "evidence_refs": [] if relation in {"unknown", "analogy"} else [deepcopy(process_ref)]})
    body["pairs"] = pairs
    inputs["expected_body_sha256"] = admission.norm_content_adjudication_sha256(body)
    pins = {body["ledger_id"]: inputs["expected_body_sha256"],
        **{body["ledger_id"] + ":admission:" + identity: item["expected_report_sha256"]
           for identity, item in admissions.items()},
        body["ledger_id"] + ":source-lane": lane._digest(inputs["source_lane"]),
        body["ledger_id"] + ":formal-lane": lane._digest(inputs["formal_lane"]),
        body["ledger_id"] + ":split": lane._digest(manifest)}
    artifacts = [{"artifact_id": identity, "artifact_sha256": digest,
        "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS}}
        for identity, digest in pins.items()]
    manifest = dependencies.build_dependency_manifest(artifacts,
        [{"dependent_id": body["ledger_id"], "dependency_id": identity}
         for identity in pins if identity != body["ledger_id"]], expected_artifact_ids=list(pins))
    inputs.update(dependency_manifest=manifest, expected_manifest_sha256=manifest["manifest_sha256"])
    result = {"preparation_inputs": inputs,
        "expected_positive_mask": [[True, True, False, False, False, False],
            [False, False, True, False, False, False], [False, False, False, True, True, False],
            [False, False, False, False, False, True]],
        "context_set_sha256": admission.norm_content_adjudication_sha256(body["context_set"]),
        "source_endpoint_snapshots_rewritten": False, "fixture_only": True,
        "actual_fit_authorized": False, "runtime_computation_proven": False}
    if not prepare:
        return result

    prepared = declarations.prepare_reviewed_relation_declaration_v4(**inputs)
    signing_subject = prepared["subject"]
    assert signing_subject["context_set_sha256"] == result["context_set_sha256"]
    assert signing_subject["scope_id"] == "contrastive-context-set:" + result["context_set_sha256"]
    contract = declarations._reviewed_contract("v4")
    slots = [*declarations.REVIEWED_SLOTS, "context_set_and_endpoint_membership"]
    assert signing_subject["context_slot_ids"] == slots
    registry = deepcopy(cases["a"]["registry"])
    registry.update(process_id="fixture:whole-context-v4-review-process", generation=2)
    for key in registry["keys"]:
        key["scope_ids"] = [signing_subject["scope_id"]]
    policy = deepcopy(cases["a"]["policy"])
    policy.update(policy_id="fixture:whole-context-v4-review-policy", process_id=registry["process_id"],
        registry_sha256=auth.digest(registry), action=contract["action"], audience=contract["audience"])
    body_ref = {"artifact_id": body["ledger_id"], "sha256": inputs["expected_body_sha256"]}
    closure = {"status": "declared_complete", "obligations": [{"slot_id": slot,
        "disposition": "resolved_by_evidence", "evidence_refs": [deepcopy(body_ref), deepcopy(process_ref)]}
        for slot in slots], "unresolved": []}
    signers, reviews = list(cases["a"]["signers"]), []
    for index, (previous, signer) in enumerate(zip(cases["a"]["reviews"], signers, strict=True)):
        claim = {key: deepcopy(value) for key, value in previous.items()
            if key not in {"signer_did", "signature_alg", "signature"}}
        claim.update(schema=contract["claim_schema"], action=contract["action"], audience=contract["audience"],
            review_id="fixture:whole-context-v4-pair-review:" + str(index),
            registry_sha256=auth.digest(registry), policy_sha256=auth.digest(policy),
            subject=deepcopy(signing_subject), context_closure=deepcopy(closure))
        claim["interpretation"].update(reviewed_graph_sha256=signing_subject["graph_sha256"],
            reviewed_ast_sha256=signing_subject["ast_sha256"],
            rationale="Fictional independently signed V4 whole-context-set pair/purpose review only.")
        reviews.append(signer.sign(claim))
    result.update(preparation=prepared, registry=registry, policy=policy, reviews=reviews, signers=signers,
        at_time_utc=cases["a"]["at_time_utc"], observed_artifacts=pins,
        observed_pins={kind: {} for kind in dependencies.PIN_KINDS},
        evidence={body["ledger_id"]: admission.norm._wire(body), process_id: process_raw},
        current_endpoint_observations={identity: {
            "observed_artifact_sha256s": deepcopy(entry["kwargs"]["observed_artifact_sha256s"]),
            "observed_pins": deepcopy(entry["kwargs"]["observed_pins"])} for identity, entry in admissions.items()})
    return result


@pytest.fixture(scope="module")
def reviewed_pairs_v4():
    return reviewed_pair_fixture_v4()


def test_reviewed_v4_context_set_binds_both_interpretations_without_granting_labels(reviewed_pairs_v4):
    case = reviewed_pairs_v4
    prepared = case['preparation']
    expected = case['preparation_inputs']['body']['context_set']
    assert len(expected) == 2
    assert expected == sorted(expected, key=lambda row: row['context_sha256'])
    assert expected[0]['scope']['interpretation_id'] != expected[1]['scope']['interpretation_id']
    assert prepared['context_set'] == expected
    assert prepared['endpoint_admission_version'] == 'v3'
    assert prepared['context_set_sha256'] == lane._digest(expected)
    assert prepared['subject']['scope_id'] == 'contrastive-context-set:' + lane._digest(expected)
    assert prepared['subject']['scope_id'] != prepared['source_endpoints'][0]['jurisdiction']
    assert prepared['subject']['context_slot_ids'] == list(subject.REVIEWED_V4_SLOTS)
    assert len(prepared['source_endpoints']) == 4 and len(prepared['formal_endpoints']) == 6
    assert prepared['semantic_label_admission'] is prepared['actual_fit_authorized'] is False
    assert prepared['legal_applicability_verified'] is prepared['controlling_authority'] is False
    replayed = subject.validate_reviewed_relation_declaration_v4(prepared,
        expected_preparation_sha256=lane._digest(prepared), **case['preparation_inputs'])
    assert replayed == prepared


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reordered', 'foreign_scope', 'changed_interpretation',
    'changed_assumptions', 'extra_field', 'wrong_digest'])
def test_reviewed_v4_requires_the_complete_exact_context_union(reviewed_pairs_v4, damage):
    inputs = deepcopy(reviewed_pairs_v4['preparation_inputs'])
    contexts = inputs['body']['context_set']
    if damage == 'missing': contexts.pop()
    elif damage == 'duplicate': contexts.append(deepcopy(contexts[0]))
    elif damage == 'reordered': contexts.reverse()
    elif damage == 'foreign_scope':
        foreign = deepcopy(contexts[0]); foreign['scope']['governing_context']['jurisdiction'] = 'fixture:foreign'
        foreign['context_sha256'] = lane._digest(foreign['scope']); contexts.append(foreign)
    elif damage == 'changed_interpretation': contexts[0]['scope']['interpretation_id'] = 'fixture:unprovided-interpretation'
    elif damage == 'changed_assumptions': contexts[0]['scope']['assumptions'] = ['unreviewed premise']
    elif damage == 'extra_field': contexts[0]['scope']['legal_applicability'] = True
    elif damage == 'wrong_digest': contexts[0]['context_sha256'] = 'f' * 64
    inputs['expected_body_sha256'] = lane._digest(inputs['body'])
    with pytest.raises(ValueError, match='context inventory'):
        subject.prepare_reviewed_relation_declaration_v4(**inputs)


@pytest.mark.parametrize('version', ['v2', 'v3'])
def test_reviewed_legacy_pair_domains_cannot_silently_adopt_v4_contexts(reviewed_pairs_v4, version):
    inputs = deepcopy(reviewed_pairs_v4['preparation_inputs'])
    inputs['body']['schema'] = subject._reviewed_contract(version)['body_schema']
    inputs['expected_body_sha256'] = lane._digest(inputs['body'])
    with pytest.raises(ValueError, match='reviewed pair declaration'):
        getattr(subject, 'prepare_reviewed_relation_declaration_' + version)(**inputs)


def test_reviewed_v3_still_refuses_cross_interpretation_even_without_inventory(reviewed_pairs_v4):
    inputs = deepcopy(reviewed_pairs_v4['preparation_inputs'])
    inputs['body'].pop('context_set')
    inputs['body']['schema'] = subject.REVIEWED_V3_BODY_SCHEMA
    inputs['expected_body_sha256'] = lane._digest(inputs['body'])
    with pytest.raises(ValueError, match='differing governing contexts'):
        subject.prepare_reviewed_relation_declaration_v3(**inputs)


def test_reviewed_v4_endpoint_scope_membership_cannot_be_relabelled(reviewed_pairs_v4):
    inputs = deepcopy(reviewed_pairs_v4['preparation_inputs'])
    endpoint = inputs['body']['source_endpoints'][0]
    endpoint['context_sha256'] = next(row['context_sha256'] for row in inputs['body']['context_set']
        if row['context_sha256'] != endpoint['context_sha256'])
    inputs['expected_body_sha256'] = lane._digest(inputs['body'])
    with pytest.raises(ValueError, match='endpoint source, formal view or context'):
        subject.prepare_reviewed_relation_declaration_v4(**inputs)


@pytest.mark.parametrize('damage', ['first_jurisdiction', 'missing_context_slot', 'changed_context_hash'])
def test_reviewed_v4_signing_subject_cannot_collapse_to_one_jurisdiction(reviewed_pairs_v4, damage):
    signing = deepcopy(reviewed_pairs_v4['preparation']['subject'])
    if damage == 'first_jurisdiction': signing['scope_id'] = reviewed_pairs_v4['preparation']['source_endpoints'][0]['jurisdiction']
    elif damage == 'missing_context_slot': signing['context_slot_ids'].pop()
    else: signing['context_set_sha256'] = 'f' * 64
    with pytest.raises(ValueError):
        subject._reviewed_subject_v4(signing, reviewed_pairs_v4['preparation_inputs']['dependency_manifest'])


def test_reviewed_v4_coherently_rehashed_foreign_scope_still_fails_complete_replay(reviewed_pairs_v4):
    prepared = deepcopy(reviewed_pairs_v4['preparation'])
    prepared['subject']['context_set_sha256'] = 'f' * 64
    prepared['subject']['scope_id'] = 'contrastive-context-set:' + 'f' * 64
    # Syntax/namespace agreement is insufficient: the inventory must also be
    # regenerated from the original independently admitted endpoint inputs.
    subject._reviewed_subject_v4(prepared['subject'],
        reviewed_pairs_v4['preparation_inputs']['dependency_manifest'])
    with pytest.raises(ValueError, match='complete replay'):
        subject.validate_reviewed_relation_declaration_v4(prepared,
            expected_preparation_sha256=lane._digest(prepared), **reviewed_pairs_v4['preparation_inputs'])


def test_reviewed_v4_statutory_pair_relabel_refuses_genuine_fictional_endpoints(reviewed_pairs_v4):
    case = reviewed_pairs_v4
    inputs = deepcopy(case['preparation_inputs'])
    prepared = subject.prepare_reviewed_relation_declaration_v4(**inputs)
    assert prepared == case['preparation']
    assert prepared['endpoint_admission_version'] == 'v3'
    assert prepared['semantic_label_admission'] is prepared['actual_fit_authorized'] is False
    assert not {'objective_positive_mask', 'objective_permitted_negative_mask',
                'production_contrastive_mask'}.intersection(prepared)
    endpoints = deepcopy(inputs['endpoint_admissions'])
    assert endpoints and all(entry['report']['provenance_kind'] == 'fictional_fixture'
        and entry['report']['training_mask'] == entry['report']['evaluation_gold_mask'] == 0
        for entry in endpoints.values())
    assert inputs['body']['provenance_kind'] == 'fictional_fixture'

    # Retag only the pair ledger. Its body/dependency commitments must agree,
    # while the genuine fictional V3 endpoint reports and replay inputs stay exact.
    old_body_sha256 = inputs['expected_body_sha256']
    body = inputs['body']
    body['provenance_kind'] = 'statutory'
    inputs['expected_body_sha256'] = lane._digest(body)
    ledger_id = body['ledger_id']
    artifact_pins = {row['artifact_id']: row['artifact_sha256']
        for row in inputs['dependency_manifest']['artifacts']}
    assert artifact_pins[ledger_id] == old_body_sha256
    artifact_pins[ledger_id] = inputs['expected_body_sha256']
    dependencies = subject._reviewed_owners('v4')[2]
    artifacts = [{'artifact_id': identity, 'artifact_sha256': digest,
                  'dependency_pins': {kind: [] for kind in dependencies.PIN_KINDS}}
        for identity, digest in artifact_pins.items()]
    manifest = dependencies.build_dependency_manifest(artifacts,
        [{'dependent_id': ledger_id, 'dependency_id': identity}
         for identity in artifact_pins if identity != ledger_id],
        expected_artifact_ids=list(artifact_pins))
    inputs.update(dependency_manifest=manifest,
                  expected_manifest_sha256=manifest['manifest_sha256'])

    # Preparation must refuse before returning any label-bearing artifact;
    # do not fabricate statutory reviews or call the mask/training owners.
    produced = []
    with pytest.raises(ValueError, match='^endpoint and pair provenance differ$'):
        produced.append(subject.prepare_reviewed_relation_declaration_v4(**inputs))
    assert produced == []
    assert inputs['endpoint_admissions'] == endpoints
    assert case['preparation_inputs']['body']['provenance_kind'] == 'fictional_fixture'
