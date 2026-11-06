"""Authored norm review transport; fixture signatures never establish legal meaning.

The source, interpretations, principals and context statements below are
fictional. No production key, statutory review or solver is used. The additive
counted cold-import guard starts one ordinary Python process.
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


# The counted companion prepares unsigned evidence only. Its authored source,
# exact original replay and assumption inventory never become a v1 subject.
def _counted_review_fixture_module():
    return _fixture("_unsigned_counted_review_source_join", "test_legal_source_typed_norm_join_v1.py")


def _counted_review_case(*, extra_issue_count=0):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    from ipfs_datasets_py.logic.autoformal import legal_source_typed_norm_join_v1 as join

    helper = _counted_review_fixture_module()
    source = helper.case(source_only=True)
    counted_request = counted.authored_counted_frame_request()
    counted_raw = helper.wire(counted_request)
    counted_report = counted.prepare_counted_frame(
        counted_raw, expected_request_sha256=sha(counted_raw))
    inventory = helper._independent_counted_paths(counted_request["expression"])
    issue_code = "unsigned_counted_carrier_frame_and_identity_unreviewed"
    rows = [{"typed_path": path,
        "source_anchor_paths": ["/unresolved/0/span"] if kind == "predicate" else [],
        "disposition": "lexical_hypothesis" if kind == "predicate" else "introduced_unresolved",
        "unresolved_codes": [issue_code],
        "rationale": "Fictional lexical custody only; counting objects, identity, frame, membership and meaning remain unresolved."}
        for path, kind, _ in inventory]
    issues = [{"code": issue_code,
        "rationale": "Every counted carrier, identity and event/time choice remains an explicit authored assumption.",
        "affected_typed_paths": [path for path, _, _ in inventory]}]
    for index in range(extra_issue_count):
        row = rows[index % len(rows)]
        code = "additional_unreviewed_counted_issue_" + str(index)
        row["unresolved_codes"].append(code)
        issues.append({"code": code, "rationale": "Separate authored unresolved assumption; retain without deduplication.",
                       "affected_typed_paths": [row["typed_path"]]})
    join_request = {"schema": "legal-source-typed-norm-join-request/v2",
        "interpretation_status": "unreviewed_correspondence_proposal",
        "component_id": "fictional:unsigned-counted-review",
        "alternative_id": "authored_counted_partial_hypothesis",
        "selected_unit_ref": deepcopy(source["join_request"]["selected_unit_ref"]),
        "node_correspondences": rows, "introduced_unresolved": issues}
    join_raw = helper.wire(join_request)
    inputs = {"scope_report": source["scope_report"], "counted_report": counted_report,
        "join_request_raw": join_raw, "expected_join_request_sha256": sha(join_raw),
        "expected_scope_report_sha256": source["kwargs"]["expected_scope_report_sha256"],
        "expected_counted_report_sha256": counted.counted_frame_report_sha256(counted_report),
        "scope_replay_inputs": source["kwargs"]["scope_replay_inputs"],
        "counted_request_raw": counted_raw, "expected_counted_request_sha256": sha(counted_raw)}
    correspondence = join.prepare_source_typed_norm_join_v2(**inputs)
    return {"arguments": {"correspondence": correspondence,
        "expected_correspondence_sha256": join.source_typed_norm_join_sha256(correspondence),
        "correspondence_inputs": inputs}, "join": join, "counted": counted,
        "source": source, "inventory": inventory}


@pytest.fixture(scope="module")
def counted_review_case():
    return _counted_review_case()


@pytest.fixture(scope="module")
def counted_review_evidence(owner, counted_review_case):
    return owner.prepare_counted_norm_review_evidence_v1(**counted_review_case["arguments"])


def _counted_review_prepare(owner, value):
    return owner.prepare_counted_norm_review_evidence_v1(**value["arguments"])


def _counted_review_validate(owner, value, report, *, expected_report_sha256=None):
    args = value["arguments"]
    return owner.validate_counted_norm_review_evidence_v1(
        report, args["correspondence"],
        expected_report_sha256=(owner.norm_review_sha256(report)
                                if expected_report_sha256 is None else expected_report_sha256),
        expected_correspondence_sha256=args["expected_correspondence_sha256"],
        correspondence_inputs=args["correspondence_inputs"])


def _unsigned_counted_keys(value):
    if type(value) is dict:
        return set(value) | set().union(*(_unsigned_counted_keys(v) for v in value.values()))
    if type(value) is list:
        return set().union(*(_unsigned_counted_keys(v) for v in value))
    return set()


def test_counted_review_public_import_and_hashing_need_no_operation_owners():
    import json
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[4]
    code = r'''
import importlib.abc, importlib.machinery, importlib.util, json, pathlib, sys, types
root = pathlib.Path(sys.argv[1])
for name in ('ipfs_datasets_py','ipfs_datasets_py.logic','ipfs_datasets_py.logic.autoformal'):
    package=types.ModuleType(name);package.__path__=[str(root/name.replace('.','/'))]
    package.__package__=name;package.__spec__=importlib.machinery.ModuleSpec(name,loader=None,is_package=True)
    sys.modules[name]=package
allowed={'ipfs_datasets_py.logic.autoformal.legal_norm_interpretation_review_v1',
         'ipfs_datasets_py.logic.autoformal.legal_norm_scope_correspondence_v1',
         'ipfs_datasets_py.logic.autoformal.legal_norm_content_responses_v1',
         'ipfs_datasets_py.logic.autoformal.legal_paired_manifest_inventory_v1'}
attempts=[]
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('ipfs_datasets_py.') and fullname not in allowed:
            attempts.append(fullname);raise AssertionError('operation import before replay: '+fullname)
sys.meta_path.insert(0,Guard())
from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as owner
assert owner.norm_review_sha256({'unsigned':'only'}) == 'd362ea238923c97be34a473d34dc8676020d78a250be3af8d55ddc152c23d840'
assert owner.__all__ == ['prepare_norm_review_evidence_v1','build_norm_review_subject_v1',
    'assess_norm_reviews_v1','validate_norm_review_assessment_v1','norm_review_sha256',
    'prepare_counted_norm_review_evidence_v1','validate_counted_norm_review_evidence_v1',
    'prepare_parent_norm_review_evidence_v1','validate_parent_norm_review_evidence_v1']
from ipfs_datasets_py.logic.autoformal import legal_norm_content_responses_v1 as content
assert content.__all__ == ['build_norm_content_template_v1','build_norm_content_response_v1',
    'assess_norm_content_responses_v1','validate_norm_content_assessment_v1','norm_content_sha256',
    'build_parent_norm_content_template_v1','validate_parent_norm_content_template_v1',
    'build_parent_norm_content_response_v1','validate_parent_norm_content_response_v1',
    'collect_parent_norm_content_responses_v1','validate_parent_norm_content_collection_v1']
assert owner.PREPARATION_SCHEMA == 'legal-norm-interpretation-review-evidence/v1'
assert owner.SUBJECT_SCHEMA == 'legal-norm-interpretation-review-subject/v1'
assert owner.CLAIM_SCHEMA == 'legal-norm-interpretation-review-signed-claim/v1'
assert owner.ACTION == 'record_norm_interpretation_review_evidence/v1'
assert owner.AUDIENCE == 'legal-autoformalization-norm-interpretation-review/v1'
print(json.dumps({'operation_imports':attempts,'exports':owner.__all__, 'content_exports':content.__all__}))
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, str(root)],
        cwd=str(root), capture_output=True, text=True, timeout=20, check=True)
    observed = json.loads(result.stdout)
    assert observed["operation_imports"] == [] and len(observed["exports"]) == 9
    assert len(observed["content_exports"]) == 11


def test_counted_review_full_public_replay_retains_original_join_and_zero_authority(
        owner, counted_review_case, counted_review_evidence, monkeypatch):
    join = counted_review_case["join"]
    actual = join.validate_source_typed_norm_join_v2
    calls = []

    def checked(*args, **kwargs):
        report = actual(*args, **kwargs)
        calls.append(report)
        return report

    monkeypatch.setattr(join, "validate_source_typed_norm_join_v2", checked)
    arguments = deepcopy(counted_review_case["arguments"])
    before = deepcopy(arguments)
    report = owner.prepare_counted_norm_review_evidence_v1(**arguments)
    assert arguments == before
    assert report == counted_review_evidence
    assert calls == [arguments["correspondence"]]
    assert _counted_review_validate(owner, counted_review_case, report) == report
    assert len(calls) == 2
    assert report["schema"] == "legal-counted-norm-review-evidence/v1"
    assert report["profile"] == "unsigned-source-counted-frame-review/v1"
    assert report["correspondence"] == before["correspondence"]
    assert report["correspondence_sha256"] == before["expected_correspondence_sha256"]
    assert all(flag is False for flag in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["external_context_not_supplied"] is True
    forbidden = {"native_ast_sha256", "native_binding", "graph_id", "graph_sha256",
                 "signature", "registry", "policy", "signer", "signable_subject"}
    assert forbidden.isdisjoint(set(report))
    assert "native_ast_sha256" not in _unsigned_counted_keys(report)


def test_counted_review_obligations_retain_every_original_group_in_order(
        owner, counted_review_case, counted_review_evidence):
    evidence = counted_review_evidence
    join = counted_review_case["arguments"]["correspondence"]
    source = join["source_scope_report"]
    groups = [
        ("original_context", source["source_context_packet"]["dependency_slots"]),
        ("original_unresolved_issue", join["original_unresolved"]),
        ("introduced_unresolved_issue", join["introduced_unresolved"]),
        ("authored_counted_assumption", join["counted_frame_report"]["assumptions"]),
        ("interpretation_question", list(owner.SEMANTIC_QUESTIONS)),
    ]
    expected = [(kind, item) for kind, values in groups for item in values]
    actual = [(row["kind"], row.get("question") if row["kind"] == "interpretation_question"
               else row["original"]) for row in evidence["obligations"]]
    assert actual == expected
    assert len(actual) == 6 + 2 + 1 + 8 + 7 == 24
    assert evidence["obligation_ids"] == [row["slot_id"] for row in evidence["obligations"]]
    assert len(set(evidence["obligation_ids"])) == len(actual)
    assert evidence["original_context_slot_ids"] == [
        row["slot_id"] for row in source["source_context_packet"]["dependency_slots"]]
    assert evidence["obligation_ids"][:6] == evidence["original_context_slot_ids"]
    assert evidence["selected_unit_ref"] == source["input_pins"]["selected_unit_ref"]


def test_counted_review_inventory_is_one_exact_reference_and_dependency_closure(
        owner, counted_review_case, counted_review_evidence):
    evidence = counted_review_evidence
    join = counted_review_case["arguments"]["correspondence"]
    assert evidence["typed_inventory"] == {
        "path": "/correspondence/provenance_ledger",
        "sha256": owner.norm_review_sha256(join["provenance_ledger"]),
        "rows": 55, "nodes": 49, "binders": 6}
    assert len(evidence["correspondence"]["provenance_ledger"]) == 55
    assert "provenance_ledger" not in evidence
    assert not any(row["kind"] in {"typed_node", "binder"} for row in evidence["obligations"])
    manifest = evidence["dependency_manifest"]
    assert dependencies.validate_dependency_manifest(manifest,
        expected_manifest_sha256=manifest["manifest_sha256"]) == manifest
    ids = evidence["required_dependency_ids"]
    assert ids == manifest["expected_artifact_ids"] == [r["artifact_id"] for r in manifest["artifacts"]]
    assert len(ids) == 12 and len(set(ids)) == 12 and len(manifest["edges"]) == 11
    assert manifest["artifacts"][0]["artifact_sha256"] == evidence["correspondence_sha256"]
    assert manifest["edges"] == [{"dependent_id": ids[0], "dependency_id": identity}
                                 for identity in ids[1:]]
    assert manifest["missing_dependencies"] == []
    observed = observations(manifest)  # Explicitly authored observations for this fixture only.
    current = dependencies.invalidate_dependencies(manifest,
        expected_manifest_sha256=manifest["manifest_sha256"], **observed)
    assert current["stale_artifact_ids"] == []
    changed = deepcopy(observed)
    changed["observed_artifact_sha256s"][ids[1]] = "0" * 64
    stale = dependencies.invalidate_dependencies(manifest,
        expected_manifest_sha256=manifest["manifest_sha256"], **changed)
    assert ids[0] in stale["stale_artifact_ids"] and ids[1] in stale["stale_artifact_ids"]
    assert stale["propagation_witnesses"]
    assert "observed_artifact_sha256s" not in evidence


def test_counted_review_original_inputs_and_returned_evidence_are_detached(owner, counted_review_case):
    args = deepcopy(counted_review_case["arguments"])
    before = deepcopy(args)
    evidence = owner.prepare_counted_norm_review_evidence_v1(**args)
    evidence["correspondence"]["counted_frame_report"]["assumptions"].append("changed returned history")
    evidence["obligations"][0]["original"]["slot_id"] += ":changed"
    assert args == before
    retained = owner.prepare_counted_norm_review_evidence_v1(**args)
    args["correspondence"]["original_unresolved"][0]["reason"] += " changed caller"
    assert retained["correspondence"] == before["correspondence"]
    assert retained["correspondence"]["typed_candidate"]["assumptions"] == \
        retained["correspondence"]["counted_frame_report"]["assumptions"]


@pytest.mark.parametrize("damage", ["correspondence_pin", "missing_input", "extra_input", "join_duplicate",
    "join_pin", "scope_pin", "counted_pin", "counted_request_duplicate", "counted_null", "raw_size_bool"])
def test_counted_review_independent_inputs_fail_before_operation_owner_discovery(
        owner, counted_review_case, monkeypatch, damage):
    args = deepcopy(counted_review_case["arguments"])
    inputs = args["correspondence_inputs"]
    if damage == "correspondence_pin": args["expected_correspondence_sha256"] = "0" * 64
    elif damage == "missing_input": inputs.pop("counted_request_raw")
    elif damage == "extra_input": inputs["context_inputs"] = None
    elif damage == "join_duplicate":
        inputs["join_request_raw"] = b'{"schema":1,"schema":2}'
        inputs["expected_join_request_sha256"] = sha(inputs["join_request_raw"])
    elif damage == "join_pin": inputs["expected_join_request_sha256"] = "0" * 64
    elif damage == "scope_pin": inputs["expected_scope_report_sha256"] = "0" * 64
    elif damage == "counted_pin": inputs["expected_counted_report_sha256"] = "0" * 64
    elif damage == "counted_request_duplicate":
        inputs["counted_request_raw"] = b'{"schema":1,"schema":2}'
        inputs["expected_counted_request_sha256"] = sha(inputs["counted_request_raw"])
    elif damage == "counted_null": inputs["counted_report"] = None
    elif damage == "raw_size_bool": inputs["scope_replay_inputs"]["expected_raw_bytes"] = True
    seen = []

    def denied():
        seen.append("operation owners")
        raise AssertionError("malformed original input reached operation owners")

    monkeypatch.setattr(owner, "_counted_review_owners", denied)
    with pytest.raises(ValueError):
        owner.prepare_counted_norm_review_evidence_v1(**args)
    assert seen == []


@pytest.mark.parametrize("damage", ["source_selector", "typed_expression", "assumption", "ledger", "source_issue"])
def test_counted_review_rehashed_join_substitution_still_requires_original_public_replay(
        owner, counted_review_case, damage):
    args = deepcopy(counted_review_case["arguments"])
    offered = args["correspondence"]
    if damage == "source_selector": offered["source_scope_report"]["source_selector"]["char_start"] += 1
    elif damage == "typed_expression": offered["typed_candidate"]["expression"]["root"]["node_id"] += ":changed"
    elif damage == "assumption": offered["counted_frame_report"]["assumptions"][0] += " changed"
    elif damage == "ledger": offered["provenance_ledger"].pop()
    elif damage == "source_issue": offered["original_unresolved"][0]["reason"] += " changed"
    args["expected_correspondence_sha256"] = owner.norm_review_sha256(offered)
    with pytest.raises(ValueError):
        owner.prepare_counted_norm_review_evidence_v1(**args)


@pytest.mark.parametrize("damage", ["obligation", "inventory", "assumption", "dependency", "authority"])
def test_counted_review_resealed_evidence_cannot_replace_full_original_regeneration(
        owner, counted_review_case, counted_review_evidence, damage):
    offered = deepcopy(counted_review_evidence)
    if damage == "obligation": offered["obligations"].pop()
    elif damage == "inventory": offered["typed_inventory"]["sha256"] = "0" * 64
    elif damage == "assumption":
        row = next(row for row in offered["obligations"] if row["kind"] == "authored_counted_assumption")
        row["original"] += " changed"
    elif damage == "dependency": offered["dependency_manifest"]["edges"].pop()
    elif damage == "authority": offered["authority"]["source_bound"] = True
    with pytest.raises(ValueError):
        _counted_review_validate(owner, counted_review_case, offered)


@pytest.mark.parametrize("location", ["correspondence", "scope_report", "counted_report"])
def test_counted_review_foreign_producer_paths_are_refused_without_reads_or_replay(
        owner, counted_review_case, monkeypatch, tmp_path, location):
    args = deepcopy(counted_review_case["arguments"])
    target = (args["correspondence"] if location == "correspondence"
              else args["correspondence_inputs"][location])
    foreign = tmp_path / "foreign-counted-review-owner.py"
    target["producer_pins"][str(foreign)] = "f" * 64
    if location == "correspondence": args["expected_correspondence_sha256"] = owner.norm_review_sha256(target)
    else: args["correspondence_inputs"]["expected_" + location + "_sha256"] = owner.norm_review_sha256(target)
    reads, calls = [], []
    original_read = Path.read_bytes

    def observed_read(path):
        if str(path) == str(foreign):
            reads.append(str(path))
            raise AssertionError("offered producer path must not be opened")
        return original_read(path)

    def denied(*args, **kwargs):
        calls.append("join replay")
        raise AssertionError("producer commitments must fail before replay")

    monkeypatch.setattr(Path, "read_bytes", observed_read)
    monkeypatch.setattr(counted_review_case["join"], "validate_source_typed_norm_join_v2", denied)
    with pytest.raises(ValueError, match="producer commitments differ"):
        owner.prepare_counted_norm_review_evidence_v1(**args)
    assert reads == calls == []


@pytest.mark.parametrize("boundary", ["join", "dependency_build", "dependency_validation", "serialization"])
@pytest.mark.parametrize("target", ["caller", "detached"])
def test_counted_review_caller_and_detached_inputs_are_fenced_at_operation_boundaries(
        owner, counted_review_case, monkeypatch, boundary, target):
    args = deepcopy(counted_review_case["arguments"])
    join = counted_review_case["join"]
    real_join = join.validate_source_typed_norm_join_v2
    real_build, real_validate = dependencies.build_dependency_manifest, dependencies.validate_dependency_manifest
    real_wire = owner._wire
    observed = {}

    def change():
        chosen = args["correspondence"] if target == "caller" else observed["detached"]
        chosen["component_id"] += ":changed-after-capture"

    def replayed(*values, **kwargs):
        result = real_join(*values, **kwargs)
        observed["detached"] = values[0]
        if boundary == "join": change()
        return result

    def built(*values, **kwargs):
        result = real_build(*values, **kwargs)
        if boundary == "dependency_build": change()
        return result

    def validated(*values, **kwargs):
        result = real_validate(*values, **kwargs)
        if boundary == "dependency_validation": change()
        return result

    def serialized(value):
        result = real_wire(value)
        if type(value) is dict and value.get("schema") == "legal-counted-norm-review-evidence/v1" \
                and boundary == "serialization":
            change()
        return result

    monkeypatch.setattr(join, "validate_source_typed_norm_join_v2", replayed)
    monkeypatch.setattr(dependencies, "build_dependency_manifest", built)
    monkeypatch.setattr(dependencies, "validate_dependency_manifest", validated)
    monkeypatch.setattr(owner, "_wire", serialized)
    with pytest.raises(ValueError, match="inputs changed"):
        owner.prepare_counted_norm_review_evidence_v1(**args)


@pytest.mark.parametrize("boundary", ["join", "dependency_build", "dependency_validation", "serialization"])
def test_counted_review_producers_are_pinned_before_replay_and_through_final_serialization(
        owner, counted_review_case, monkeypatch, boundary):
    args = deepcopy(counted_review_case["arguments"])
    join = counted_review_case["join"]
    real_join, real_pins = join.validate_source_typed_norm_join_v2, owner._counted_review_pins
    real_build, real_validate = dependencies.build_dependency_manifest, dependencies.validate_dependency_manifest
    real_wire = owner._wire
    changed, events = False, []
    monkeypatch.setattr(owner, "_COUNTED_REVIEW_OWNER_PINS", None)

    def replayed(*values, **kwargs):
        nonlocal changed
        events.append("join")
        result = real_join(*values, **kwargs)
        if boundary == "join": changed = True
        return result

    def built(*values, **kwargs):
        nonlocal changed
        result = real_build(*values, **kwargs)
        if boundary == "dependency_build": changed = True
        return result

    def validated(*values, **kwargs):
        nonlocal changed
        result = real_validate(*values, **kwargs)
        if boundary == "dependency_validation": changed = True
        return result

    def serialized(value):
        nonlocal changed
        result = real_wire(value)
        if type(value) is dict and value.get("schema") == "legal-counted-norm-review-evidence/v1" \
                and boundary == "serialization":
            changed = True
        return result

    def observed(*values, **kwargs):
        events.append("pins")
        result = dict(real_pins(*values, **kwargs))
        if changed: result[next(iter(result))] = "0" * 64
        return result

    monkeypatch.setattr(join, "validate_source_typed_norm_join_v2", replayed)
    monkeypatch.setattr(dependencies, "build_dependency_manifest", built)
    monkeypatch.setattr(dependencies, "validate_dependency_manifest", validated)
    monkeypatch.setattr(owner, "_wire", serialized)
    monkeypatch.setattr(owner, "_counted_review_pins", observed)
    with pytest.raises(ValueError, match="producers changed"):
        owner.prepare_counted_norm_review_evidence_v1(**args)
    assert events[0] == "pins" and events.index("pins") < events.index("join")


def test_counted_review_genuine_join_over_512_obligations_is_refused_without_truncation(owner, monkeypatch):
    value = _counted_review_case(extra_issue_count=489)
    joined = value["arguments"]["correspondence"]
    expected = (len(joined["source_scope_report"]["source_context_packet"]["dependency_slots"])
        + len(joined["original_unresolved"]) + len(joined["introduced_unresolved"])
        + len(joined["counted_frame_report"]["assumptions"]) + len(owner.SEMANTIC_QUESTIONS))
    assert expected == 513 and len(joined["provenance_ledger"]) == 55
    real = value["join"].validate_source_typed_norm_join_v2
    calls = []

    def replayed(*args, **kwargs):
        result = real(*args, **kwargs)
        calls.append(result)
        return result

    monkeypatch.setattr(value["join"], "validate_source_typed_norm_join_v2", replayed)
    with pytest.raises(ValueError, match="obligation bound exceeded"):
        _counted_review_prepare(owner, value)
    assert calls == [joined]


@pytest.mark.parametrize("pin_case", ["wrong", "bool"])
def test_counted_review_output_pin_is_independent_before_replay(
        owner, counted_review_case, counted_review_evidence, monkeypatch, pin_case):
    def denied():
        raise AssertionError("independent report pin must fail before operation owners")

    monkeypatch.setattr(owner, "_counted_review_owners", denied)
    pin = "0" * 64 if pin_case == "wrong" else True
    with pytest.raises(ValueError):
        _counted_review_validate(owner, counted_review_case, counted_review_evidence,
                                 expected_report_sha256=pin)


def test_counted_review_lowered_input_bound_refuses_without_large_allocation(owner, counted_review_case, monkeypatch):
    monkeypatch.setattr(owner, "MAX_INPUT_BYTES", 32)
    with pytest.raises(ValueError, match="bound"):
        _counted_review_prepare(owner, counted_review_case)


def test_counted_review_unsigned_profile_cannot_enter_unchanged_v1_subject_builder(
        owner, base, counted_review_evidence):
    kwargs = deepcopy(base["build_arguments"])
    kwargs["expected_preparation_sha256"] = owner.norm_review_sha256(counted_review_evidence)
    with pytest.raises(ValueError, match="norm preparation differs"):
        owner.build_norm_review_subject_v1(counted_review_evidence, base["manifest"], **kwargs)


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_counted_review_validator_fences_offered_report_through_regeneration(
        owner, counted_review_case, counted_review_evidence, monkeypatch, target):
    offered = deepcopy(counted_review_evidence)
    real_prepare, real_snapshot = owner.prepare_counted_norm_review_evidence_v1, owner._snapshot
    captured = {}

    def snapshotted(value, **kwargs):
        result = real_snapshot(value, **kwargs)
        if type(value) is dict and set(value) == {"report", "correspondence", "inputs"} \
                and "report" not in captured:
            captured["report"] = result[0]["report"]
        return result

    def regenerated(*args, **kwargs):
        result = real_prepare(*args, **kwargs)
        chosen = offered if target == "caller" else captured["report"]
        chosen["obligations"][0]["original"]["slot_id"] += ":changed-during-validation"
        return result

    monkeypatch.setattr(owner, "_snapshot", snapshotted)
    monkeypatch.setattr(owner, "prepare_counted_norm_review_evidence_v1", regenerated)
    with pytest.raises(ValueError, match="validation inputs changed"):
        _counted_review_validate(owner, counted_review_case, offered)


@pytest.mark.parametrize("damage", ["changed_bytes", "foreign_origin"])
def test_counted_review_first_call_rejects_stale_preimported_dependency_owner(
        owner, counted_review_case, monkeypatch, tmp_path, damage):
    # The dependency module is already imported above. A fresh review module
    # must still bind its reviewed source before establishing a first baseline.
    name = "ipfs_datasets_py.logic.autoformal._unsigned_counted_review_first_call"
    spec = importlib.util.spec_from_file_location(name, Path(owner.__file__))
    cold = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cold)
    assert cold._COUNTED_REVIEW_OWNER_PINS is None
    actual_path = Path(dependencies.__file__).resolve()
    actual_bytes = actual_path.read_bytes()
    original_read = Path.read_bytes
    foreign = tmp_path / "foreign-preimported-dependency.py"
    foreign.write_bytes(actual_bytes)
    calls = []

    def read(path):
        if str(path) == str(foreign):
            raise AssertionError("a foreign dependency origin must not be opened")
        if str(path) == str(actual_path) and damage == "changed_bytes":
            return actual_bytes + b"\n# Authored stale-source observation.\n"
        return original_read(path)

    def denied(*args, **kwargs):
        calls.append("join replay")
        raise AssertionError("dependency identity must fail before the first replay")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read)
        patch.setattr(counted_review_case["join"], "validate_source_typed_norm_join_v2", denied)
        if damage == "foreign_origin": patch.setattr(dependencies, "__file__", str(foreign))
        with pytest.raises(ValueError, match="dependenc"):
            cold.prepare_counted_norm_review_evidence_v1(**deepcopy(counted_review_case["arguments"]))
    assert calls == []
    assert cold._COUNTED_REVIEW_OWNER_PINS is None


# Parent review is an unsigned consumer of genuine complete physical replay.
# These fixtures do not turn literal accounting into reviewed legal meaning.
def parent_review_materialize(owner, tmp_path, *, selected=0, source_value=None):
    source = fixture.scope_fixture.parent_case(tmp_path, selected=selected) if source_value is None else source_value
    value = fixture.parent_correspondence_case(tmp_path, source_value=source)
    correspondence_report = fixture.parent_correspondence_prepare(value)
    positional, keyword = fixture.parent_correspondence_arguments(value)
    inputs = dict(scope_report=positional[0], relational_report=positional[1],
                  mapping_request_raw=positional[2], **keyword)
    arguments = dict(correspondence=correspondence_report,
        expected_correspondence_sha256=correspondence.norm_scope_correspondence_sha256(correspondence_report),
        correspondence_inputs=inputs)
    preparation = owner.prepare_parent_norm_review_evidence_v1(**arguments)
    return dict(value=value, arguments=arguments, preparation=preparation)


def parent_review_validate(owner, value, report=None, *, expected_report_sha256=None):
    report = value["preparation"] if report is None else report
    return owner.validate_parent_norm_review_evidence_v1(report,
        expected_report_sha256=(owner.norm_review_sha256(report)
            if expected_report_sha256 is None else expected_report_sha256), **value["arguments"])


def assert_parent_review_unqualified(report):
    assert report["authority"] and all(item is False for item in report["authority"].values())
    for key in ("training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0
    assert report["governing_definition_use"] is None
    assert report["norm_interpretation_ready"] is False


def test_parent_review_genuine_occurrence_obligations_and_dependency_graph(owner, tmp_path):
    value = parent_review_materialize(owner, tmp_path)
    report = value["preparation"]; supplied = value["arguments"]["correspondence"]
    scope = supplied["source_scope"]; binding = scope["parent_source_binding"]
    assert report["schema"] == owner.PARENT_PREPARATION_SCHEMA
    assert report["profile"] == owner.PARENT_REVIEW_PROFILE
    assert report["correspondence"] == supplied
    assert report["source_rows"] == supplied["request"]["source_rows"]
    assert report["typed_context_inventory"] == supplied["typed_context_inventory"]
    assert scope["source_selector"]["start_char"] > 0
    assert "Clérk" in scope["source_selector"]["span_text"]
    assert "café" in scope["source_selector"]["span_text"]
    expected_identity = dict(schema="legal-parent-norm-review-source-identity/v1",
        parent_manifest_cid=binding["parent_manifest_cid"],
        source_version_cid=binding["source_version"]["record_cid"],
        source_occurrence_cid=binding["selector"]["record_cid"],
        companion_record_cid=binding["companion_record"]["record_cid"],
        context_record_cid=binding["context"]["record_cid"],
        source_binding_sha256=binding["source_binding_sha256"])
    assert report["source_identity"] == expected_identity
    assert report["source_identity_sha256"] == owner.norm_review_sha256(expected_identity)
    context = binding["context"]
    assert report["original_parent_context"] == context
    assert context["availability"] == "required_unavailable" and len(context["missing_requirements"]) == 6
    obligations = report["obligations"]
    assert len(obligations) == 14 and len({row["slot_id"] for row in obligations}) == 14
    assert report["obligation_ids"] == [row["slot_id"] for row in obligations]
    assert report["context_obligation_ids"] == [row["slot_id"] for row in obligations[:6]]
    for ordinal, row in enumerate(obligations[:6]):
        missing = context["missing_requirements"][ordinal]
        ids = {key: expected_identity[key] for key in
               ("source_version_cid", "source_occurrence_cid", "context_record_cid")}
        original = dict(schema="legal-parent-norm-review-context-requirement/v1", **ids,
            requirement_ordinal=ordinal, missing_requirement=missing, context=context)
        identity = dict(schema="legal-parent-norm-review-context-id/v1", **ids,
            requirement_ordinal=ordinal, missing_requirement=missing)
        assert row == dict(slot_id="parent-norm-context:" + owner.norm_review_sha256(identity),
                           kind="original_parent_context", original=original)
    assert obligations[6]["kind"] == "original_unresolved_issue"
    assert obligations[6]["original"] == supplied["retained_unresolved"][0]
    assert [row["question"] for row in obligations[7:]] == list(owner.SEMANTIC_QUESTIONS)
    manifest = report["dependency_manifest"]
    assert manifest["expected_artifact_ids"] == report["required_dependency_ids"]
    assert not manifest["missing_dependencies"]
    observed = observations(manifest)
    observed["observed_artifact_sha256s"][report["required_dependency_ids"][-1]] = "0" * 64
    stale = dependencies.invalidate_dependencies(manifest,
        expected_manifest_sha256=manifest["manifest_sha256"], **observed)
    assert report["required_dependency_ids"][0] in stale["stale_artifact_ids"]
    assert_parent_review_unqualified(report)
    assert parent_review_validate(owner, value) == report


@pytest.mark.parametrize("selected", [1, 2])
def test_parent_review_identical_literals_keep_occurrence_and_physical_row_identity(owner, tmp_path, selected):
    left = parent_review_materialize(owner, tmp_path, selected=0)
    original_source = left["value"]["source"]; physical = original_source["physical"]
    companion = original_source["companions"][selected]
    right_source = dict(original_source,
        arguments=physical.binding_arguments(original_source["original"], companion),
        source=physical.bind(original_source["original"], companion))
    right = parent_review_materialize(owner, tmp_path, source_value=right_source)
    a, b = left["preparation"], right["preparation"]
    assert a["correspondence"]["source_scope"]["scope_request"]["source_text"] == \
        b["correspondence"]["source_scope"]["scope_request"]["source_text"]
    left_binding = a["correspondence"]["source_scope"]["parent_source_binding"]
    right_binding = b["correspondence"]["source_scope"]["parent_source_binding"]
    assert left_binding["parent_record"]["source_identity"]["row_ordinal"] == 0
    assert right_binding["parent_record"]["source_identity"]["row_ordinal"] == selected // 2
    assert a["source_identity"]["source_occurrence_cid"] != b["source_identity"]["source_occurrence_cid"]
    assert a["source_identity_sha256"] != b["source_identity_sha256"]
    assert set(a["context_obligation_ids"]).isdisjoint(b["context_obligation_ids"])
    with pytest.raises(ValueError):
        parent_review_validate(owner, right, a)


@pytest.mark.parametrize("damage", ["selector", "context", "typed", "coverage", "schema", "request_bytes"])
def test_parent_review_resealed_original_evidence_still_requires_full_replay(owner, tmp_path, damage):
    value = parent_review_materialize(owner, tmp_path); arguments = deepcopy(value["arguments"])
    offered = arguments["correspondence"]
    if damage == "selector": offered["source_scope"]["source_selector"]["start_char"] += 1
    elif damage == "context": offered["source_scope"]["parent_source_binding"]["context"]["missing_requirements"].pop()
    elif damage == "typed": offered["request"]["typed_rows"].pop()
    elif damage == "coverage": offered["source_scope"]["scope_declaration"]["coverage"]["declared_status"] = "complete"
    elif damage == "schema": offered["schema"] = correspondence.SCHEMA
    else:
        replay = arguments["correspondence_inputs"]["scope_replay_inputs"]
        request = deepcopy(offered["source_scope"]["scope_request"])
        request["source_text"] += " changed"
        replay["scope_request_raw"] = fixture.wire(request)
        replay["expected_scope_request_sha256"] = sha(replay["scope_request_raw"])
    arguments["expected_correspondence_sha256"] = owner.norm_review_sha256(offered)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**arguments)


@pytest.mark.parametrize("damage", ["pin", "missing", "duplicate", "bound"])
def test_parent_review_bounded_preflight_refuses_before_operation_owner_discovery(owner, tmp_path, monkeypatch, damage):
    value = parent_review_materialize(owner, tmp_path); arguments = deepcopy(value["arguments"])
    if damage == "pin": arguments["expected_correspondence_sha256"] = "0" * 64
    elif damage == "missing": arguments["correspondence_inputs"].pop("relational_request_raw")
    elif damage == "duplicate":
        arguments["correspondence_inputs"]["mapping_request_raw"] = b'{"schema":1,"schema":2}'
        arguments["correspondence_inputs"]["expected_mapping_request_sha256"] = sha(arguments["correspondence_inputs"]["mapping_request_raw"])
    else: monkeypatch.setattr(owner, "MAX_BYTES", 128)
    calls = []
    def denied():
        calls.append("operation owners")
        raise AssertionError("malformed parent input reached operation owners")
    monkeypatch.setattr(owner, "_parent_review_owners", denied)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**arguments)
    assert calls == []


def test_parent_review_foreign_producer_path_is_not_opened_or_replayed(owner, tmp_path, monkeypatch):
    value = parent_review_materialize(owner, tmp_path); arguments = deepcopy(value["arguments"])
    foreign = tmp_path / "foreign-parent-review-owner.py"
    arguments["correspondence"]["producer_pins"][str(foreign)] = "f" * 64
    arguments["expected_correspondence_sha256"] = owner.norm_review_sha256(arguments["correspondence"])
    reads, calls = [], []; real_read = Path.read_bytes
    def observed_read(path):
        if str(path) == str(foreign):
            reads.append(str(path)); raise AssertionError("untrusted producer path opened")
        return real_read(path)
    def denied(*args, **kwargs):
        calls.append("correspondence replay"); raise AssertionError("untrusted generation reached replay")
    monkeypatch.setattr(Path, "read_bytes", observed_read)
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", denied)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**arguments)
    assert reads == calls == []


@pytest.mark.parametrize("damage", ["drop_obligation", "dependency", "promote"])
def test_parent_review_resealed_result_cannot_replace_complete_regeneration(owner, tmp_path, damage):
    value = parent_review_materialize(owner, tmp_path); report = deepcopy(value["preparation"])
    if damage == "drop_obligation": report["obligations"].pop()
    elif damage == "dependency": report["dependency_manifest"]["edges"].pop()
    else: report["authority"]["source_semantics_verified"] = True
    with pytest.raises(ValueError):
        parent_review_validate(owner, value, report)


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_parent_review_late_inputs_are_fenced_after_genuine_correspondence_replay(owner, tmp_path, monkeypatch, target):
    value = parent_review_materialize(owner, tmp_path); arguments = deepcopy(value["arguments"])
    real = correspondence.validate_norm_scope_correspondence_v2; observed = []
    def replay_then_change(*args, **kwargs):
        result = real(*args, **kwargs)
        if not observed:
            chosen = arguments["correspondence"] if target == "caller" else args[0]
            chosen["alternative_id"] += ":late"
            observed.append("genuine_correspondence_replayed")
        return result
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", replay_then_change)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**arguments)
    assert observed == ["genuine_correspondence_replayed"]


def test_parent_review_late_physical_source_change_is_refused(owner, tmp_path, monkeypatch):
    value = parent_review_materialize(owner, tmp_path); real = correspondence.validate_norm_scope_correspondence_v2
    parquet = next(tmp_path.rglob("laws.parquet")); original = parquet.read_bytes(); observed = []
    def replay_then_change(*args, **kwargs):
        result = real(*args, **kwargs)
        if not observed:
            parquet.write_bytes(original + b"\nchanged after original replay\n")
            observed.append("genuine_correspondence_replayed")
        return result
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", replay_then_change)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**value["arguments"])
    assert observed and parquet.read_bytes() != original


def test_parent_review_final_detached_output_change_is_refused(owner, tmp_path, monkeypatch):
    value = parent_review_materialize(owner, tmp_path); real_wire = owner._wire; observed = []; objects = set()
    def encoded_then_change(report):
        encoded = real_wire(report)
        if type(report) is dict and report.get("schema") == owner.PARENT_PREPARATION_SCHEMA:
            objects.add(id(report))
            if len(objects) > 1 and not observed:
                report["training_mask"] = True; observed.append("parent_review_serialized")
        return encoded
    monkeypatch.setattr(owner, "_wire", encoded_then_change)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**value["arguments"])
    assert observed == ["parent_review_serialized"]


def test_parent_review_primary_error_keeps_secondary_closeout_note(owner, tmp_path, monkeypatch):
    value = parent_review_materialize(owner, tmp_path); arguments = deepcopy(value["arguments"])
    real = correspondence.validate_norm_scope_correspondence_v2; observed = []
    def replay_then_primary(*args, **kwargs):
        real(*args, **kwargs); observed.append("genuine_correspondence_replayed")
        arguments["correspondence"]["alternative_id"] += ":late"
        raise ValueError("primary authored parent review failure")
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", replay_then_primary)
    with pytest.raises(ValueError) as caught:
        owner.prepare_parent_norm_review_evidence_v1(**arguments)
    assert str(caught.value) == "primary authored parent review failure"
    assert observed and any("secondary" in note for note in getattr(caught.value, "__notes__", []))


def test_parent_review_mutated_genuine_delegate_result_is_refused(owner, tmp_path, monkeypatch):
    value = parent_review_materialize(owner, tmp_path); real = correspondence.validate_norm_scope_correspondence_v2; observed = []
    def replay_then_change_returned(*args, **kwargs):
        result = real(*args, **kwargs)
        if not observed:
            result["alternative_id"] += ":changed-returned-delegate"
            observed.append("genuine_correspondence_replayed")
        return result
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", replay_then_change_returned)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**value["arguments"])
    assert observed == ["genuine_correspondence_replayed"]


@pytest.mark.parametrize("damage", [
    "last_producer_output", "last_producer_caller", "last_producer_detached", "final_encoder_input",
])
def test_parent_review_reuse_final_boundaries(owner, tmp_path, monkeypatch, damage):
    """Keep one peer profile while guarding its last real callback/encoder."""
    value = parent_review_materialize(owner, tmp_path)
    arguments = deepcopy(value["arguments"])
    actual_loads, actual_pins, actual_wire = owner.json.loads, owner._parent_review_pins, owner._wire
    actual_replay = correspondence.validate_norm_scope_correspondence_v2
    captured, detached_replay, closing, changed = [], [], [], []

    def capture(*args, **kwargs):
        result = actual_loads(*args, **kwargs)
        if type(result) is dict and result.get("schema") == owner.PARENT_PREPARATION_SCHEMA:
            captured.append(result)
        return result

    def genuine_replay(*args, **kwargs):
        result = actual_replay(*args, **kwargs)
        if not detached_replay:
            detached_replay.append(kwargs["scope_replay_inputs"])
        return result

    def after_genuine_pins(*args, **kwargs):
        result = actual_pins(*args, **kwargs)
        if captured:
            closing.append("genuine closing producer check")
            # The final of three genuine closing fences follows the last
            # original replay. Earlier boundary checks must stay unchanged.
            if len(closing) == 3 and damage != "final_encoder_input":
                if damage == "last_producer_output":
                    captured[-1]["training_mask"] = False
                else:
                    replay = (arguments["correspondence_inputs"]["scope_replay_inputs"]
                              if damage == "last_producer_caller" else detached_replay[0])
                    replay["scope_request_raw"] += b" "
                changed.append(damage)
        return result

    def after_genuine_encoding(report):
        raw = actual_wire(report)
        if damage == "final_encoder_input" and captured and report is captured[-1] and not changed:
            arguments["correspondence_inputs"]["mapping_request_raw"] += b" "
            changed.append(damage)
        return raw

    monkeypatch.setattr(owner.json, "loads", capture)
    monkeypatch.setattr(correspondence, "validate_norm_scope_correspondence_v2", genuine_replay)
    monkeypatch.setattr(owner, "_parent_review_pins", after_genuine_pins)
    monkeypatch.setattr(owner, "_wire", after_genuine_encoding)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**arguments)
    assert detached_replay and changed == [damage]


def test_parent_review_reuse_last_producer_cannot_change_retained_manifest(owner, tmp_path, monkeypatch):
    value = parent_review_materialize(owner, tmp_path)
    arguments = deepcopy(value["arguments"])
    actual_loads, actual_pins = owner.json.loads, owner._parent_review_pins
    actual_build = dependencies.build_dependency_manifest
    captured, retained, closing, changed = [], [], [], []

    def capture(*args, **kwargs):
        result = actual_loads(*args, **kwargs)
        if type(result) is dict and result.get("schema") == owner.PARENT_PREPARATION_SCHEMA:
            captured.append(result)
        return result

    def genuine_build(*args, **kwargs):
        result = actual_build(*args, **kwargs)
        retained.append(result)
        return result

    def after_genuine_pins(*args, **kwargs):
        result = actual_pins(*args, **kwargs)
        if captured:
            closing.append("genuine closing producer check")
            if len(closing) == 3:
                assert len(retained) == 2
                retained[0]["manifest_sha256"] = "0" * 64
                changed.append("retained genuine builder result")
        return result

    monkeypatch.setattr(owner.json, "loads", capture)
    monkeypatch.setattr(dependencies, "build_dependency_manifest", genuine_build)
    monkeypatch.setattr(owner, "_parent_review_pins", after_genuine_pins)
    with pytest.raises(ValueError):
        owner.prepare_parent_norm_review_evidence_v1(**arguments)
    assert changed == ["retained genuine builder result"]


def test_parent_review_reuse_fingerprint_matches_original_snapshot_without_encoder(owner, tmp_path, monkeypatch):
    value = parent_review_materialize(owner, tmp_path)
    original = dict(**deepcopy(value["arguments"]), offered=None, expected_report_sha256=None)
    detached, commitment = owner._snapshot(original)

    def forbidden_general_encoder(*args, **kwargs):
        raise AssertionError("final commitment must bypass the general correspondence encoder")

    monkeypatch.setattr(correspondence, "_wire", forbidden_general_encoder)
    assert owner._parent_review_fingerprint(original) == commitment
    assert owner._parent_review_fingerprint(detached) == commitment
