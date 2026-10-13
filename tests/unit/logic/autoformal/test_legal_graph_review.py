"""Synthetic cryptographic fixtures; no human reviews, gold or trusted keys.

Even the test exercising the external-policy wire shape uses generated fixture
keys and fictional HTML. No result is published as production review authority.
"""
from copy import deepcopy
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization

from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as review
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graphs
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as contexts
from ipfs_datasets_py.logic.profile_g import Ed25519Signer

NOW = "2026-10-13T16:00:00Z"
START = "2026-10-01T00:00:00Z"
END = "2026-11-01T00:00:00Z"
TEXT = "Agency must file notice."
RAW = (f'<meta charset="utf-8"><h3 class="section-head">§1. Fictional signature fixture</h3>'
       f'<p class="statutory-body">(a) {TEXT}</p>'
       f'<p class="statutory-body">(b) {TEXT}</p>').encode()


def artifact(identity, sha):
    return {"artifact_id": identity, "artifact_sha256": sha,
            "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS}}


def refresh(case):
    case["policy"]["registry_sha256"] = review.digest(case["registry"])
    for index, old in enumerate(case["reviews"]):
        body = {key: deepcopy(value) for key, value in old.items() if key not in ("signer_did", "signature_alg", "signature")}
        body["registry_sha256"] = review.digest(case["registry"])
        body["policy_sha256"] = review.digest(case["policy"])
        case["reviews"][index] = case["signers"][index].sign(body)


@pytest.fixture
def case():
    document = contexts.extract_document(RAW, url="https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm",
                                         edition=2024, legal_id="usc:us:10:1")
    selector = contexts.exact_view_occurrences(document, RAW, text=TEXT)[0]
    source = graphs.bind_source_occurrence(document, RAW, selector=selector, document_revision="fictional-release-2024")
    scope = graphs.bind_scope(jurisdiction="US", instrument="fictional-10-USC-1", edition=2024,
                              applicability="fixture-only", definition_scope="fictional-section-1")
    ast = {"rules": [{"modality": "O", "actor": "Agency", "action": "file", "object": "notice",
                      "conditions": [], "exceptions": [], "temporal": []}]}
    graph = graphs.build_graph(ast, profile="canonical_rules_v1", source=source, scope=scope)
    packet = contexts.build_context_packet(document, RAW, char_start=selector["char_start"], char_end=selector["char_end"])
    records = [artifact(graph["graph_id"], review.digest(graph)), artifact("fixture:definition", "b" * 64),
               artifact("fixture:authority", "c" * 64), artifact("fixture:independent", "d" * 64)]
    records[1]["dependency_pins"]["definition"] = [{"key": "fixture:definition-source", "sha256": "e" * 64}]
    manifest = dependencies.build_dependency_manifest(records, [
        {"dependent_id": graph["graph_id"], "dependency_id": "fixture:definition"},
        {"dependent_id": "fixture:definition", "dependency_id": "fixture:authority"}],
        expected_artifact_ids=[row["artifact_id"] for row in records])
    builder = {"expected_graph_sha256": review.digest(graph), "expected_context_sha256": review.digest(packet),
        "expected_manifest_sha256": manifest["manifest_sha256"], "document": document, "raw_html": RAW,
        "required_dependency_ids": [graph["graph_id"], "fixture:definition", "fixture:authority"]}
    subject = review.build_review_subject(graph, packet, manifest, **builder)
    signers = [Ed25519Signer.generate("did:example:fixture-legal"), Ed25519Signer.generate("did:example:fixture-formal")]
    keys = [{"key_id": "fixture:key:" + str(i), "signer_did": signer.did,
        "public_key_hex": signer.public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(),
        "principal_id": "fixture:principal:" + str(i), "roles": [role], "scope_ids": [scope["scope_id"]],
        "valid_from_utc": START, "valid_until_utc": END, "revoked_at_utc": None}
        for i, (signer, role) in enumerate(zip(signers, review.ROLES))]
    registry = {"schema": review.REGISTRY_SCHEMA, "mode": "synthetic_fixture", "process_id": "fixture:review-process",
        "generation": 3, "revocation_generation": 2, "valid_from_utc": START, "valid_until_utc": END,
        "keys": keys, "revoked_principals": []}
    policy = {"schema": review.POLICY_SCHEMA, "mode": "synthetic_fixture", "policy_id": "fixture:policy",
        "process_id": registry["process_id"], "registry_sha256": review.digest(registry), "action": review.ACTION,
        "audience": review.AUDIENCE, "required_roles": list(review.ROLES), "valid_from_utc": START,
        "valid_until_utc": END, "max_review_age_seconds": 86400}
    evidence = {"fixture:context-rationale": b"Fictional context dispositions for signature engineering only."}
    closure = {"status": "declared_complete", "obligations": [{"slot_id": slot, "disposition": "not_applicable",
        "evidence_refs": [{"artifact_id": "fixture:context-rationale", "sha256": hashlib.sha256(evidence["fixture:context-rationale"]).hexdigest()}]}
        for slot in subject["context_slot_ids"]], "unresolved": []}
    reviews = [signer.sign({"schema": review.CLAIM_SCHEMA, "action": review.ACTION, "audience": review.AUDIENCE,
        "review_id": "fixture:review:" + str(i), "key_id": keys[i]["key_id"], "principal_id": keys[i]["principal_id"],
        "role": role, "registry_sha256": review.digest(registry), "policy_sha256": review.digest(policy),
        "issued_at_utc": "2026-10-13T15:00:00Z", "expires_at_utc": "2026-10-14T15:00:00Z",
        "subject": deepcopy(subject), "interpretation": {"decision": "support", "reviewed_graph_sha256": review.digest(graph),
            "reviewed_ast_sha256": review.digest(ast), "rationale": "Synthetic signature fixture only.", "ambiguity": []},
        "context_closure": deepcopy(closure)}) for i, (signer, role) in enumerate(zip(signers, review.ROLES))]
    observed_pins = {kind: {} for kind in dependencies.PIN_KINDS}
    observed_pins["definition"]["fixture:definition-source"] = "e" * 64
    return {"graph": graph, "packet": packet, "manifest": manifest, "builder": builder, "subject": subject,
        "registry": registry, "policy": policy, "reviews": reviews, "signers": signers, "evidence": evidence,
        "observed_artifacts": {row["artifact_id"]: row["artifact_sha256"] for row in records}, "observed_pins": observed_pins}


def arguments(case):
    return (case["subject"], case["registry"], case["policy"], case["reviews"], case["manifest"]), {
        "expected_subject_sha256": review.digest(case["subject"]), "expected_registry_sha256": review.digest(case["registry"]),
        "expected_policy_sha256": review.digest(case["policy"]), "expected_reviews_sha256": review.digest(case["reviews"]),
        "expected_manifest_sha256": case["manifest"]["manifest_sha256"], "at_time_utc": NOW,
        "observed_artifact_sha256s": case["observed_artifacts"], "observed_pins": case["observed_pins"],
        "evidence_artifacts": case["evidence"]}


def assess(case):
    args, kwargs = arguments(case)
    return review.assess_graph_reviews(*args, **kwargs)


def test_real_profile_g_signatures_authenticate_fixture_bytes_without_admission(case):
    result = assess(case)
    assert result["evidence_assessment_status"] == "authenticated"
    assert result["authenticated_evidence_count"] == 2
    assert all(row["signature_status"] == "valid" for row in result["reviews"])
    assert "production_trust_registry_unavailable" in result["blockers"]
    assert result["review_prerequisites_satisfied_under_selected_trust"] is False
    assert result["accepted_view_eligible"] is False
    assert all(result[field] is False for field in review.FALSE_AUTHORITY)
    args, kwargs = arguments(case)
    assert review.validate_review_assessment(result, *args, **kwargs) == result


def test_external_policy_wire_shape_only_satisfies_review_prerequisites_and_still_blocks_lean(case):
    case["registry"]["mode"] = case["policy"]["mode"] = "external_pinned_trust"
    refresh(case)
    result = assess(case)
    assert result["review_prerequisites_satisfied_under_selected_trust"] is True
    assert result["accepted_view_eligible"] is False and result["admitted"] is False
    assert result["blockers"] == ["downstream_Lean_kernel_admission_required", "downstream_semantic_validation_required"]
    assert result["human_identity_verified"] is False and result["human_independence_verified"] is False


@pytest.mark.parametrize("field", ["graph_sha256", "ast_sha256", "source_binding_sha256", "source_occurrence_id",
    "document_revision", "scope_id", "context_packet_sha256", "dependency_manifest_sha256"])
def test_resigned_wrong_subject_cannot_retarget_selected_graph_context_or_revision(case, field):
    case["reviews"][0]["subject"][field] = "0" * 64
    refresh(case)
    result = assess(case)
    assert result["reviews"][0]["status"] == "rejected"
    assert "signed_subject_differs" in result["reviews"][0]["blockers"]


@pytest.mark.parametrize("damage,blocker", [("signature", "signature_invalid"), ("role", "unauthorized_review_role"),
    ("scope", "unauthorized_legal_scope"), ("key_revoked", "key_revoked"), ("principal_revoked", "principal_revoked"),
    ("key_expired", "key_not_current_for_review_interval"), ("review_expired", "review_not_current"),
    ("future_review", "review_not_current"), ("stale_review", "review_age_exceeded"),
    ("registry_expired", "registry_not_current"), ("policy_expired", "policy_not_current")])
def test_authentication_enforces_signature_roles_current_authority_and_revocations(case, damage, blocker):
    if damage == "signature": case["reviews"][0]["interpretation"]["rationale"] += " unsigned edit"
    else:
        key = case["registry"]["keys"][0]
        if damage == "role": key["roles"] = ["formal_review"]
        elif damage == "scope": key["scope_ids"] = ["legal-scope:sha256:" + "0" * 64]
        elif damage == "key_revoked": key["revoked_at_utc"] = NOW
        elif damage == "principal_revoked": case["registry"]["revoked_principals"] = [{"principal_id": key["principal_id"], "revoked_at_utc": NOW}]
        elif damage == "key_expired": key["valid_until_utc"] = NOW
        elif damage == "review_expired": case["reviews"][0]["expires_at_utc"] = NOW
        elif damage == "future_review": case["reviews"][0]["issued_at_utc"] = "2026-10-13T17:00:00Z"
        elif damage == "stale_review": case["policy"]["max_review_age_seconds"] = 10
        elif damage == "registry_expired": case["registry"]["valid_until_utc"] = NOW
        elif damage == "policy_expired": case["policy"]["valid_until_utc"] = NOW
        refresh(case)
    result = assess(case)
    assert blocker in result["reviews"][0]["blockers"]
    assert result["reviews"][0]["status"] == "rejected"


def test_same_authorized_principal_with_two_different_keys_is_not_independent(case):
    case["registry"]["keys"][1]["principal_id"] = case["registry"]["keys"][0]["principal_id"]
    case["reviews"][1]["principal_id"] = case["registry"]["keys"][0]["principal_id"]
    refresh(case)
    result = assess(case)
    assert result["authenticated_evidence_count"] == 2
    assert "distinct_authorized_review_principals_missing" in result["blockers"]


@pytest.mark.parametrize("authority,boundary", [("registry", "issuance"), ("policy", "issuance"),
                                               ("registry", "expiry"), ("policy", "expiry")])
def test_full_signed_interval_must_fit_both_selected_authority_windows(case, authority, boundary):
    if boundary == "issuance": case[authority]["valid_from_utc"] = "2026-10-13T15:30:00Z"
    else: case[authority]["valid_until_utc"] = "2026-10-14T00:00:00Z"
    refresh(case)
    result = assess(case)
    assert result["reviews"][0]["signature_status"] == "valid"
    assert result["reviews"][0]["status"] == "rejected"
    assert authority + "_not_current_for_review_interval" in result["reviews"][0]["blockers"]


def test_shared_raw_key_and_duplicate_review_population_cannot_fake_independence(case):
    case["registry"]["keys"][1]["public_key_hex"] = case["registry"]["keys"][0]["public_key_hex"]
    refresh(case)
    with pytest.raises(ValueError, match="duplicate review key"): assess(case)


@pytest.mark.parametrize("damage", ["omit_slot", "open_slot", "no_evidence", "changed_evidence", "unresolved"])
def test_authenticated_signature_never_closes_incomplete_context_obligations(case, damage):
    closure = case["reviews"][0]["context_closure"]
    if damage == "omit_slot": closure["obligations"].pop()
    elif damage == "open_slot": closure["obligations"][0]["disposition"] = "open"
    elif damage == "no_evidence": closure["obligations"][0]["evidence_refs"] = []
    elif damage == "changed_evidence": case["evidence"]["fixture:context-rationale"] += b" changed"
    else: closure["unresolved"] = ["Needs external legal context."]
    refresh(case)
    result = assess(case)
    assert result["reviews"][0]["status"] == "authenticated"
    assert result["reviews"][0]["signed_context_declaration_complete"] is False
    assert "authenticated_complete_context_declarations_missing" in result["blockers"]
    assert result["context_closure_verified"] is False


@pytest.mark.parametrize("damage", ["artifact", "definition_pin", "missing_artifact"])
def test_current_dependency_closure_is_rechecked_at_assessment(case, damage):
    if damage == "artifact": case["observed_artifacts"]["fixture:authority"] = "f" * 64
    elif damage == "definition_pin": case["observed_pins"]["definition"].clear()
    else: case["observed_artifacts"]["fixture:authority"] = None
    result = assess(case)
    assert result["authenticated_evidence_count"] == 2
    assert "required_dependency_closure_not_current" in result["blockers"]


def test_unrelated_stale_artifact_does_not_block_the_selected_declared_closure(case):
    case["registry"]["mode"] = case["policy"]["mode"] = "external_pinned_trust"
    case["observed_artifacts"]["fixture:independent"] = None
    refresh(case)
    assert assess(case)["review_prerequisites_satisfied_under_selected_trust"] is True


def test_dropped_dependency_even_resealed_subject_and_resigned_reviews_is_refused(case):
    case["subject"]["required_dependency_ids"].pop()
    case["subject"]["dependency_artifacts"].pop()
    for row in case["reviews"]: row["subject"] = deepcopy(case["subject"])
    refresh(case)
    with pytest.raises(ValueError, match="required dependency closure"): assess(case)


def test_population_pins_prevent_review_removal_or_trust_registry_substitution(case):
    args, kwargs = arguments(case)
    removed = case["reviews"][:1]
    with pytest.raises(ValueError, match="complete review population"):
        review.assess_graph_reviews(case["subject"], case["registry"], case["policy"], removed, case["manifest"], **kwargs)
    case["registry"]["generation"] += 1
    with pytest.raises(ValueError, match="pinned trust input"):
        review.assess_graph_reviews(*args, **kwargs)


def test_authenticated_conflict_or_ambiguity_blocks_review_prerequisites(case):
    case["reviews"][1]["interpretation"]["decision"] = "reject"
    refresh(case)
    result = assess(case)
    assert "authenticated_review_conflict_or_ambiguity" in result["blockers"]
    assert result["accepted_view_eligible"] is False


def test_missing_backend_and_missing_reviews_are_pending_without_authority(case, monkeypatch):
    monkeypatch.setattr(review, "_verify_signature", lambda *args: "backend_unavailable")
    result = assess(case)
    assert result["evidence_assessment_status"] == "pending"
    assert all(row["status"] == "pending" for row in result["reviews"])
    case["reviews"] = []
    result = assess(case)
    assert result["evidence_assessment_status"] == "pending"
    assert "authenticated_legal_review_missing" in result["blockers"]


def test_resealed_assessment_cannot_promote_signature_status_or_acceptance(case):
    result = assess(case)
    result["accepted_view_eligible"] = True
    result["blockers"] = []
    result["assessment_sha256"] = review.digest({key: value for key, value in result.items() if key != "assessment_sha256"})
    args, kwargs = arguments(case)
    with pytest.raises(ValueError, match="exact regeneration"):
        review.validate_review_assessment(result, *args, **kwargs)


def test_source_builder_rejects_retargeted_identical_text_occurrence_and_bad_population(case):
    other = contexts.exact_view_occurrences(case["builder"]["document"], RAW, text=TEXT)[1]
    source = graphs.bind_source_occurrence(case["builder"]["document"], RAW, selector=other, document_revision="fictional-release-2024")
    ast = graphs.graph_to_ast(case["graph"])
    changed = graphs.build_graph(ast, profile="canonical_rules_v1", source=source, scope=case["graph"]["scope"])
    with pytest.raises(ValueError, match="pinned graph or context"):
        review.build_review_subject(changed, case["packet"], case["manifest"], **case["builder"])
    wrong = {**case["builder"], "required_dependency_ids": [case["graph"]["graph_id"]]}
    with pytest.raises(ValueError, match="dependency population"):
        review.build_review_subject(case["graph"], case["packet"], case["manifest"], **wrong)


@pytest.mark.parametrize("origin,damage", [("graph", "omitted_edge"), ("graph", "hash"),
                                           ("assertion", "omitted_edge"), ("assertion", "hash")])
def test_initial_subject_reconciles_graph_and_assertion_dependencies_even_under_new_manifest_pins(case, origin, damage):
    ref = {"artifact_id": "fixture:definition", "artifact_sha256": "b" * 64, "role": "governing-definition"}
    options = {"dependency_refs": [ref]} if origin == "graph" else {"semantic_declarations": {
        "entities": [{"entity_key": name, "kind": "concept", "label": name, "source_selector": None,
                      "definition_kind": None, "ast_path": None, "ambiguity": [], "evidence_refs": []}
                     for name in ("actor", "definition")],
        "assertions": [{"assertion_key": "fixture:assertion", "subject_key": "actor", "predicate": "uses",
                        "object_keys": ["definition"], "ambiguity": [], "evidence_refs": [], "dependency_refs": [ref]}]}}
    graph = graphs.build_graph(graphs.graph_to_ast(case["graph"]), profile="canonical_rules_v1",
        source=case["graph"]["source"], scope=case["graph"]["scope"], **options)
    records = [artifact(graph["graph_id"], review.digest(graph)), artifact("fixture:definition", "b" * 64)]
    edges = [{"dependent_id": graph["graph_id"], "dependency_id": "fixture:definition"}]
    manifest = dependencies.build_dependency_manifest(records, edges, expected_artifact_ids=[r["artifact_id"] for r in records])
    builder = {**case["builder"], "expected_graph_sha256": review.digest(graph),
               "expected_manifest_sha256": manifest["manifest_sha256"],
               "required_dependency_ids": [graph["graph_id"], "fixture:definition"]}
    subject = review.build_review_subject(graph, case["packet"], manifest, **builder)
    assert subject["graph_declared_dependency_refs"][0]["reference"] == ref
    if damage == "omitted_edge": edges = []; builder["required_dependency_ids"] = [graph["graph_id"]]
    else: records[1]["artifact_sha256"] = "f" * 64
    changed = dependencies.build_dependency_manifest(records, edges, expected_artifact_ids=[r["artifact_id"] for r in records])
    builder["expected_manifest_sha256"] = changed["manifest_sha256"]
    with pytest.raises(ValueError, match="graph-declared dependency"):
        review.build_review_subject(graph, case["packet"], changed, **builder)


def test_noncanonical_signature_bounds_and_unknown_authority_flags_are_refused(case, monkeypatch):
    case["reviews"][0]["passed"] = True
    with pytest.raises(ValueError, match="closed signed graph review"): assess(case)
    case["reviews"][0].pop("passed")
    case["reviews"][0]["signature"] += "="
    with pytest.raises(ValueError, match="canonical detached"): assess(case)
    monkeypatch.setattr(review, "MAX_REVIEWS", 1)
    with pytest.raises(ValueError, match="complete review population"): assess(case)


def test_outputs_are_detached_from_caller_review_and_evidence_maps(case):
    result = assess(case)
    original = deepcopy(result)
    case["reviews"][0]["interpretation"]["ambiguity"].append("Caller mutation")
    case["evidence"].clear()
    assert result == original
