"""Authored norm review transport; fixture signatures never establish legal meaning.

The source, interpretations, principals and context statements below are
fictional. No production key, statutory review, solver or subprocess is used.
"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as signatures
from ipfs_datasets_py.logic.autoformal import legal_norm_scope_correspondence_v1 as correspondence
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as sampling_review
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review_context as contextual


def _fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


fixture = _fixture("_norm_review_authored_correspondence", "test_legal_norm_scope_correspondence_v1.py")
START, END = "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
NOW, ISSUED, EXPIRES = "2026-10-15T12:00:00Z", "2026-10-15T11:00:00Z", "2026-10-16T11:00:00Z"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def original_inputs(value):
    args, kwargs = fixture.arguments(value)
    return dict(scope_report=args[0], relational_report=args[1], mapping_request_raw=args[2], **kwargs)


def context_for(value):
    """Two fully replayed sources; an explicit nomination, never a definition use."""
    target = value["source"]
    supporting = fixture.scope_fixture.case(edition=2023)
    sources = []
    for source in (target, supporting):
        replay = deepcopy(source["args"])
        if "limits" in replay:
            replay["sampling_limits"] = replay.pop("limits")
        replay["expected_sampling_report_sha256"] = fixture.digest(source["sampling"])
        bundle = sampling_review.prepare_sampling_review_bundle(source["raw"], **replay)
        sources.append(dict(bundle=bundle, raw=source["raw"],
                            expected_bundle_sha256=sampling_review.sampling_review_bundle_sha256(bundle),
                            replay_inputs=replay))
    refs = []
    for entry, source in zip(sources, (target, supporting), strict=True):
        refs.append(next(guide["subject_ref"] for guide in entry["bundle"]["guides"]
                         if guide["subject_ref"]["kind"] == "unit"
                         and guide["subject_ref"]["sha256"] == fixture.digest(source["unit"])))
    attachments = [{"target_bundle_sha256": sources[0]["expected_bundle_sha256"],
                    "target_subject_ref": refs[0],
                    "supporting_bundle_sha256": sources[1]["expected_bundle_sha256"],
                    "supporting_subject_ref": refs[1],
                    "role": "Fictional contextual comparison; applicability and definition use unresolved."}]
    pin = fixture.digest(attachments)
    packet = contextual.prepare(sources, attachments, expected_attachments_sha256=pin)
    return dict(packet=packet, sources=sources, attachments=attachments,
                expected_context_sha256=contextual.packet_sha256(packet),
                expected_attachments_sha256=pin, limits=None)


def preparation_arguments(value, *, with_context=False):
    report = fixture.prepare(value)
    return dict(correspondence=report,
                expected_correspondence_sha256=correspondence.norm_scope_correspondence_sha256(report),
                correspondence_inputs=original_inputs(value),
                context_inputs=context_for(value) if with_context else None)


def materialize(owner, *, with_context=False, sufficient=False):
    value = fixture.case(sufficient=sufficient)
    args = preparation_arguments(value, with_context=with_context)
    preparation = owner.prepare_norm_review_evidence_v1(**args)
    manifest = dependencies.build_dependency_manifest(preparation["artifacts"], preparation["edges"],
        expected_artifact_ids=[row["artifact_id"] for row in preparation["artifacts"]])
    build = dict(expected_preparation_sha256=owner.norm_review_sha256(preparation),
                 expected_manifest_sha256=manifest["manifest_sha256"],
                 required_dependency_ids=preparation["required_dependency_ids"], **args)
    subject = owner.build_norm_review_subject_v1(preparation, manifest, **build)
    return dict(value=value, arguments=args, preparation=preparation, manifest=manifest,
                build_arguments=build, subject=subject)


def observations(manifest):
    pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for row in manifest["artifacts"]:
        for kind, entries in row["dependency_pins"].items():
            pins[kind].update({entry["key"]: entry["sha256"] for entry in entries})
    return dict(observed_artifact_sha256s={row["artifact_id"]: row["artifact_sha256"]
                                         for row in manifest["artifacts"]}, observed_pins=pins)


def pending(owner, materialized):
    data = deepcopy(materialized)
    registry = dict(schema=signatures.REGISTRY_SCHEMA, mode="unavailable", process_id="fixture:norm-process",
                    generation=1, revocation_generation=1, valid_from_utc=START, valid_until_utc=END,
                    keys=[], revoked_principals=[])
    policy = dict(schema=signatures.POLICY_SCHEMA, mode="unavailable", policy_id="fixture:norm-policy",
                  process_id=registry["process_id"], registry_sha256=signatures.digest(registry),
                  action=owner.ACTION, audience=owner.AUDIENCE, required_roles=list(signatures.ROLES),
                  valid_from_utc=START, valid_until_utc=END, max_review_age_seconds=86400)
    data.update(registry=registry, policy=policy, reviews=[], evidence_artifacts={},
                **observations(data["manifest"]))
    return data


def assessment_arguments(owner, data):
    return (data["subject"], data["registry"], data["policy"], data["reviews"], data["manifest"]), dict(
        **data["arguments"], preparation=data["preparation"],
        expected_preparation_sha256=owner.norm_review_sha256(data["preparation"]),
        expected_subject_sha256=owner.norm_review_sha256(data["subject"]),
        expected_registry_sha256=signatures.digest(data["registry"]),
        expected_policy_sha256=signatures.digest(data["policy"]),
        expected_reviews_sha256=signatures.digest(data["reviews"]),
        expected_manifest_sha256=data["manifest"]["manifest_sha256"], at_time_utc=NOW,
        observed_artifact_sha256s=data["observed_artifact_sha256s"], observed_pins=data["observed_pins"],
        evidence_artifacts=data["evidence_artifacts"])


def assess(owner, data):
    args, kwargs = assessment_arguments(owner, data)
    return owner.assess_norm_reviews_v1(*args, **kwargs)


def refresh(data):
    data["policy"]["registry_sha256"] = signatures.digest(data["registry"])
    for index, claim in enumerate(data["reviews"]):
        body = {key: deepcopy(value) for key, value in claim.items()
                if key not in {"signer_did", "signature_alg", "signature"}}
        body.update(registry_sha256=signatures.digest(data["registry"]),
                    policy_sha256=signatures.digest(data["policy"]))
        data["reviews"][index] = data["signers"][index].sign(body)


def synthetic(owner, materialized):
    from cryptography.hazmat.primitives import serialization
    from ipfs_datasets_py.logic.profile_g import Ed25519Signer

    data = pending(owner, materialized)
    data["registry"]["mode"] = data["policy"]["mode"] = "synthetic_fixture"
    data["signers"] = [Ed25519Signer.generate("did:example:norm-legal-fixture"),
                       Ed25519Signer.generate("did:example:norm-formal-fixture")]
    keys = []
    for index, (signer, role) in enumerate(zip(data["signers"], signatures.ROLES, strict=True)):
        keys.append(dict(key_id="fixture:norm-key:" + str(index), signer_did=signer.did,
                         public_key_hex=signer.public_key.public_bytes(serialization.Encoding.Raw,
                            serialization.PublicFormat.Raw).hex(), principal_id="fixture:norm-principal:" + str(index),
                         roles=[role], scope_ids=[data["subject"]["scope_id"]],
                         valid_from_utc=START, valid_until_utc=END, revoked_at_utc=None))
    data["registry"]["keys"] = keys
    evidence_id = "fixture:norm-context"
    data["evidence_artifacts"] = {evidence_id: b"Synthetic context declaration; no statutory meaning or human review."}
    closure = dict(status="declared_complete", unresolved=[], obligations=[
        dict(slot_id=slot, disposition="not_applicable", evidence_refs=[
            dict(artifact_id=evidence_id, sha256=sha(data["evidence_artifacts"][evidence_id]))])
        for slot in data["subject"]["context_slot_ids"]])
    data["reviews"] = [dict(schema=owner.CLAIM_SCHEMA, action=owner.ACTION, audience=owner.AUDIENCE,
        review_id="fixture:norm-review:" + str(index), key_id=keys[index]["key_id"],
        principal_id=keys[index]["principal_id"], role=role, issued_at_utc=ISSUED, expires_at_utc=EXPIRES,
        subject=deepcopy(data["subject"]), context_closure=deepcopy(closure),
        interpretation=dict(decision="support", reviewed_graph_sha256=data["subject"]["graph_sha256"],
            reviewed_ast_sha256=data["subject"]["ast_sha256"],
            rationale="Fictional authentication engineering only; no accepted legal interpretation.", ambiguity=[]))
        for index, role in enumerate(signatures.ROLES)]
    refresh(data)
    return data


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1
    return legal_norm_interpretation_review_v1


@pytest.fixture(scope="module")
def base(owner):
    return materialize(owner)


@pytest.fixture
def signed(owner, base):
    return synthetic(owner, base)


def test_preparation_and_pending_assessment_preserve_originals_and_every_obligation(owner, base):
    before = deepcopy(base)
    preparation = base["preparation"]
    scope = base["arguments"]["correspondence"]["source_scope"]
    assert preparation["correspondence"] == base["arguments"]["correspondence"]
    assert preparation["graph_sha256"] == base["arguments"]["expected_correspondence_sha256"]
    assert len(preparation["context_slot_ids"]) == 6 + len(scope["scope_declaration"]["unresolved"]) + 7
    assert len(set(preparation["context_slot_ids"])) == len(preparation["context_slot_ids"])
    assert len(preparation["obligations"]) == len(preparation["context_slot_ids"])
    fixture.assert_no_authority(preparation)
    data = pending(owner, base)
    report = assess(owner, data)
    assert report["evidence_assessment_status"] == "pending"
    assert report["review_count"] == report["authenticated_evidence_count"] == 0
    assert report["norm_interpretation_ready"] is False
    assert report["norm_readiness_blockers"]
    assert report["accepted_view_eligible"] is report["admitted"] is False
    args, kwargs = assessment_arguments(owner, data)
    assert owner.validate_norm_review_assessment_v1(report, *args, **kwargs) == report
    assert base == before


def test_authored_context_nomination_replays_without_closing_definition_or_source_meaning(owner):
    data = materialize(owner, with_context=True)
    report = assess(owner, pending(owner, data))
    assert data["preparation"]["context_evidence"] is not None
    assert data["preparation"]["correspondence"] == data["arguments"]["correspondence"]
    assert data["preparation"]["correspondence"]["governing_definition_use"] is None
    assert report["norm_interpretation_ready"] is False
    fixture.assert_no_authority(data["preparation"])


def test_compact_subject_preserves_deep_legal_ast_without_changing_signature_json_contract(owner, monkeypatch):
    """Full replay retains admissible AST depth; signed bytes contain exact pins."""
    original = fixture.authored_request
    ast = fixture.relational_fixture.ast

    def deeply_nested(**kwargs):
        request = original(**kwargs)
        expression = ast.TypedExpression.from_dict(request["expression"])
        root = expression.root
        for index in range(18):
            root = ast.mk_not("fixture:deep-review:" + str(index), root)
        request["expression"] = ast.TypedExpression(expression.expression_id, root, expression.signature).to_dict()
        return request

    monkeypatch.setattr(fixture, "authored_request", deeply_nested)
    data = materialize(owner)
    expression = data["arguments"]["correspondence"]["relational_fragment"]["typed_expression"]
    assert expression["root"]["kind"] == "not"
    assert data["preparation"]["correspondence"]["relational_fragment"]["typed_expression"] == expression
    with pytest.raises(ValueError, match="depth/node"):
        signatures.wire(data["preparation"])
    assert signatures.wire(data["subject"])
    report = assess(owner, pending(owner, data))
    assert report["norm_interpretation_ready"] is False
    assert report["authenticated_evidence_count"] == 0


@pytest.mark.parametrize("damage", ["scope", "raw", "unresolved", "authority", "request_bytes", "foreign_context"])
def test_independent_correspondence_replay_refuses_rehashed_input_substitution(owner, base, damage):
    args = deepcopy(base["arguments"])
    if damage == "scope": args["correspondence_inputs"]["scope_report"]["declared_semantic_coverage"] = "complete"
    elif damage == "raw": args["correspondence_inputs"]["scope_replay_inputs"]["raw_html"] += b" "
    elif damage == "unresolved": args["correspondence"]["retained_unresolved"] = []
    elif damage == "authority": args["correspondence"]["authority"]["admitted"] = True
    elif damage == "request_bytes": args["correspondence_inputs"]["mapping_request_raw"] += b" "
    elif damage == "foreign_context":
        other = fixture.case(edition=2025)
        args["context_inputs"] = context_for(other)
    args["expected_correspondence_sha256"] = correspondence.norm_scope_correspondence_sha256(args["correspondence"])
    with pytest.raises(ValueError):
        owner.prepare_norm_review_evidence_v1(**args)


@pytest.mark.parametrize("field", ["ast_sha256", "native_ast_sha256", "scope_id", "context_slot_ids", "obligations", "producer_pins", "authority"])
def test_rehashed_preparation_cannot_replace_full_replay(owner, base, field):
    preparation, kwargs = deepcopy(base["preparation"]), deepcopy(base["build_arguments"])
    if field.endswith("sha256"): preparation[field] = "0" * 64
    elif field == "scope_id": preparation[field] = "fixture:foreign-scope"
    elif field in {"context_slot_ids", "obligations"}: preparation[field].pop()
    elif field == "producer_pins": preparation[field] = {}
    else: preparation[field][next(iter(preparation[field]))] = 0
    kwargs["expected_preparation_sha256"] = owner.norm_review_sha256(preparation)
    with pytest.raises(ValueError):
        owner.build_norm_review_subject_v1(preparation, base["manifest"], **kwargs)


@pytest.mark.parametrize("field", ["native_ast_sha256", "scope_id", "context_slot_ids", "required_dependency_ids"])
def test_rehashed_subject_cannot_replace_preparation_or_dependency_closure(owner, base, field):
    data = pending(owner, base)
    if field.endswith("sha256"): data["subject"][field] = "0" * 64
    elif field == "scope_id": data["subject"][field] = "fixture:foreign-scope"
    else: data["subject"][field].pop()
    with pytest.raises(ValueError):
        assess(owner, data)


def test_synthetic_signatures_authenticate_bytes_but_never_promote_partial_meaning(owner, signed):
    report = assess(owner, signed)
    assert report["authenticated_evidence_count"] == 2
    assert all(row["signature_status"] == "valid" for row in report["reviews"])
    assert "production_trust_registry_unavailable" in report["blockers"]
    assert report["norm_interpretation_ready"] is False and report["norm_readiness_blockers"]
    assert report["accepted_view_eligible"] is report["training_qualified"] is report["admitted"] is False


def test_external_wire_shape_is_only_fixture_and_cannot_erase_original_semantic_obligations(owner, signed):
    signed["registry"]["mode"] = signed["policy"]["mode"] = "external_pinned_trust"
    refresh(signed)
    report = assess(owner, signed)
    assert report["authenticated_evidence_count"] == 2
    assert report["norm_interpretation_ready"] is False
    assert report["norm_readiness_blockers"]
    assert report["source_semantics_verified"] is report["context_closure_verified"] is False
    assert report["human_identity_verified"] is report["human_independence_verified"] is False


@pytest.mark.parametrize("field", ["schema", "action", "audience"])
def test_old_graph_domain_cannot_sign_new_norm_interpretation(owner, signed, field):
    signed["reviews"][0][field] = {"schema": signatures.CLAIM_SCHEMA, "action": signatures.ACTION,
                                  "audience": signatures.AUDIENCE}[field]
    refresh(signed)
    with pytest.raises(ValueError):
        assess(owner, signed)


@pytest.mark.parametrize("damage,blocker", [
    ("signature", "signature_invalid"), ("role", "unauthorized_review_role"),
    ("scope", "unauthorized_legal_scope"), ("unknown", "unknown_authorized_key"),
    ("revoked", "key_revoked"), ("principal_revoked", "principal_revoked"),
    ("expired", "review_not_current"), ("subject", "signed_subject_differs"),
])
def test_signatures_scope_authority_and_subject_are_independently_checked(owner, signed, damage, blocker):
    if damage == "signature": signed["reviews"][0]["interpretation"]["rationale"] += " unsigned edit"
    else:
        key = signed["registry"]["keys"][0]
        if damage == "role": key["roles"] = ["formal_review"]
        elif damage == "scope": key["scope_ids"] = ["fixture:foreign-scope"]
        elif damage == "unknown": signed["reviews"][0]["key_id"] = "fixture:unknown-key"
        elif damage == "revoked": key["revoked_at_utc"] = NOW
        elif damage == "principal_revoked": signed["registry"]["revoked_principals"] = [dict(principal_id=key["principal_id"], revoked_at_utc=NOW)]
        elif damage == "expired": signed["reviews"][0]["expires_at_utc"] = NOW
        elif damage == "subject": signed["reviews"][0]["subject"]["native_ast_sha256"] = "0" * 64
        refresh(signed)
    report = assess(owner, signed)
    assert blocker in report["reviews"][0]["blockers"]
    assert report["reviews"][0]["status"] == "rejected"


@pytest.mark.parametrize("damage,blocker", [
    ("missing_slot", "context_obligation_population_differs"),
    ("slot_order", "context_obligation_population_differs"),
    ("open", "context_obligation_unresolved"),
    ("missing_evidence", "context_evidence_missing_or_changed"),
    ("changed_evidence", "context_evidence_missing_or_changed"),
])
def test_signed_context_claims_need_complete_ordered_slots_and_exact_evidence(owner, signed, damage, blocker):
    closure = signed["reviews"][0]["context_closure"]
    if damage == "missing_slot": closure["obligations"].pop()
    elif damage == "slot_order": closure["obligations"].reverse()
    elif damage == "open": closure["obligations"][0]["disposition"] = "open"
    elif damage == "missing_evidence": signed["evidence_artifacts"] = {}
    elif damage == "changed_evidence": signed["evidence_artifacts"]["fixture:norm-context"] += b" changed"
    refresh(signed)
    report = assess(owner, signed)
    assert blocker in report["reviews"][0]["context_blockers"]
    assert report["review_prerequisites_satisfied_under_selected_trust"] is False


def test_same_principal_cannot_supply_independent_legal_and_formal_review(owner, signed):
    signed["registry"]["keys"][1]["principal_id"] = signed["registry"]["keys"][0]["principal_id"]
    signed["reviews"][1]["principal_id"] = signed["reviews"][0]["principal_id"]
    refresh(signed)
    report = assess(owner, signed)
    assert "distinct_authorized_review_principals_missing" in report["blockers"]


@pytest.mark.parametrize("damage", ["artifact", "producer"])
def test_current_observations_invalidate_stale_correspondence_and_owner_bytes(owner, signed, damage):
    if damage == "artifact": signed["observed_artifact_sha256s"][signed["subject"]["graph_id"]] = "0" * 64
    else:
        policy = signed["observed_pins"]["policy"]
        assert policy
        policy[next(iter(policy))] = "0" * 64
    report = assess(owner, signed)
    assert "required_dependency_closure_not_current" in report["blockers"]


def test_saved_assessment_cannot_gain_authority_by_rehashing(owner, base):
    data = pending(owner, base)
    report = assess(owner, data)
    report["norm_interpretation_ready"] = True
    body = {key: value for key, value in report.items() if key != "assessment_sha256"}
    report["assessment_sha256"] = signatures.digest(body)
    args, kwargs = assessment_arguments(owner, data)
    with pytest.raises(ValueError):
        owner.validate_norm_review_assessment_v1(report, *args, **kwargs)


@pytest.mark.parametrize("damage", ["missing_replay", "mapping_json", "mapping_pin", "scope_json", "raw_size_bool"])
def test_malformed_source_inputs_fail_before_review_operation_owners_load(owner, base, monkeypatch, damage):
    args = deepcopy(base["arguments"])
    replay = args["correspondence_inputs"]
    if damage == "missing_replay": replay.pop("scope_replay_inputs")
    elif damage == "mapping_json":
        replay["mapping_request_raw"] = b'{"schema":1,"schema":2}'
        replay["expected_mapping_request_sha256"] = sha(replay["mapping_request_raw"])
    elif damage == "mapping_pin": replay["expected_mapping_request_sha256"] = "0" * 64
    elif damage == "scope_json":
        replay["scope_replay_inputs"]["scope_request_raw"] = b'{"source_text":'
        replay["scope_replay_inputs"]["expected_scope_request_sha256"] = sha(
            replay["scope_replay_inputs"]["scope_request_raw"])
    elif damage == "raw_size_bool": replay["scope_replay_inputs"]["expected_raw_bytes"] = True
    calls = []

    def denied():
        calls.append("review owners")
        raise AssertionError("malformed original inputs must fail before review owners load")

    monkeypatch.setattr(owner, "_owners", denied)
    with pytest.raises(ValueError):
        owner.prepare_norm_review_evidence_v1(**args)
    assert calls == []


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_preparation_fences_source_inputs_across_correspondence_replay(owner, base, monkeypatch, target):
    args = deepcopy(base["arguments"])
    validate = correspondence.validate_norm_scope_correspondence_v1

    def mutating(*positional, **keywords):
        result = validate(*positional, **keywords)
        destination = (args["correspondence_inputs"]["scope_replay_inputs"]
                       if target == "caller" else keywords["scope_replay_inputs"])
        destination["expected_raw_bytes"] += 1
        return result

    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v1", mutating)
    with pytest.raises(ValueError, match="inputs changed"):
        owner.prepare_norm_review_evidence_v1(**args)


def test_preparation_fences_producers_after_context_replay(owner, base, monkeypatch):
    source_context, pins = owner._source_context, owner._pins
    changed = False

    def mutating(*args, **kwargs):
        nonlocal changed
        result = source_context(*args, **kwargs)
        changed = True
        return result

    def observed(owners):
        result = dict(pins(owners))
        if changed:
            result[next(iter(result))] = "0" * 64
        return result

    monkeypatch.setattr(owner, "_source_context", mutating)
    monkeypatch.setattr(owner, "_pins", observed)
    with pytest.raises(ValueError, match="producers changed"):
        owner.prepare_norm_review_evidence_v1(**deepcopy(base["arguments"]))


def test_first_preparation_pins_review_owner_before_correspondence_replay(owner, base, monkeypatch, tmp_path):
    """A first-call baseline must precede operations that could change owners."""
    module = contextual
    original_bytes = Path(module.__file__).read_bytes()
    copied = tmp_path / "sampling_review_owner.py"
    copied.write_bytes(original_bytes)
    monkeypatch.setattr(module, "__file__", str(copied))
    monkeypatch.setattr(owner, "_OWNER_PINS", None)
    validate = correspondence.validate_norm_scope_correspondence_v1
    calls = []

    def mutating(*args, **kwargs):
        result = validate(*args, **kwargs)
        calls.append("correspondence replay completed")
        copied.write_bytes(original_bytes + b"\n# Authored first-call mutation fixture.\n")
        return result

    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v1", mutating)
    with pytest.raises(ValueError, match="producers changed"):
        owner.prepare_norm_review_evidence_v1(**deepcopy(base["arguments"]))
    assert calls == ["correspondence replay completed"]


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_authentication_fences_complete_trust_inputs(owner, base, monkeypatch, target):
    data = pending(owner, base)
    verifier = signatures._assess_reviews

    def mutating(subject, registry, *args, **kwargs):
        result = verifier(subject, registry, *args, **kwargs)
        destination = data["registry"] if target == "caller" else registry
        destination["generation"] += 1
        return result

    monkeypatch.setattr(signatures, "_assess_reviews", mutating)
    with pytest.raises(ValueError, match="inputs changed"):
        assess(owner, data)


def test_authentication_fences_producers_after_signature_assessment(owner, base, monkeypatch):
    verifier, pins = signatures._assess_reviews, owner._pins
    changed = False

    def mutating(*args, **kwargs):
        nonlocal changed
        result = verifier(*args, **kwargs)
        changed = True
        return result

    def observed(owners):
        result = dict(pins(owners))
        if changed:
            result[next(iter(result))] = "0" * 64
        return result

    monkeypatch.setattr(signatures, "_assess_reviews", mutating)
    monkeypatch.setattr(owner, "_pins", observed)
    with pytest.raises(ValueError, match="producer changed"):
        assess(owner, pending(owner, base))
