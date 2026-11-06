"""Complete source-review cohorts cannot hide conflicting source participants.

All sources, signers, and declarations here are fictional engineering fixtures.
Successful authentication never applies a source decision or establishes law.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_adjudication as adjudication
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_responses as responses
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review as source
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust
from ipfs_datasets_py.logic.profile_g import Ed25519Signer
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def helper():
    spec = importlib.util.spec_from_file_location(
        "authored_legacy_adjudication_for_complete_source_cohorts",
        Path(__file__).with_name("test_corpus_legacy_source_adjudication.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_cohort

    return corpus_legacy_source_cohort


def source_population(bank, count):
    """Create complete, distinct physical rows sharing one producer receipt."""
    join_helper = helper().helper().helper().fixture_helper()
    raw_rows, producers, sections, expected_sections = [], [], [], []
    for index in range(count):
        tag = f"{bank}:{index}"
        raw, inputs = join_helper.fixture(f"§ Fictional {tag}: Clerk; Clerk.", "Clerk")
        producer = json.loads(inputs["producer_receipt_bytes"])["rows"][0]
        legal_id = f"usc:fixture:{bank}:{index}"
        artifact_sha256 = sha(("fictional source artifact " + tag).encode())
        entry_cid = cid_for_bytes(("fictional physical row " + tag).encode())
        for field in ("source_sections", "expected_source_sections"):
            inputs[field][0].update(artifact_sha256=artifact_sha256,
                                    parquet_row_index=17 + index,
                                    entry_cid=entry_cid, legal_id=legal_id)
        producer.update(source_span_id="fictional-span:" + tag, entry_cid=entry_cid,
                        legal_id=legal_id, source_section_offset=17 + index)
        producer["source_parent"]["sha256"] = artifact_sha256
        row = json.loads(raw[0])
        row["observation_id"] = "fictional-observation:" + tag
        row["source"].update(span_id=producer["source_span_id"], legal_id=legal_id)
        row["source_target_artifact_pointer"] = f"/rows/{index}/logic_target_observation"
        raw_rows.append(row)
        producers.append(producer)
        sections.extend(inputs["source_sections"])
        expected_sections.extend(inputs["expected_source_sections"])
    receipt = wire({"schema_version": "fictional-producer/v1", "rows": producers})
    rows = []
    for row in raw_rows:
        row["source_target_artifact_sha256"] = sha(receipt)
        rows.append(wire(row))
    inputs = {
        "expected_population": [{"row_sha256": sha(raw),
            "source_span_id": row["source"]["span_id"], "text_sha256": row["source"]["text_sha256"],
            "source_revision": row["source"]["revision"]} for row, raw in zip(raw_rows, rows, strict=True)],
        "producer_receipt_bytes": receipt, "expected_producer_receipt_sha256": sha(receipt),
        "source_sections": sections, "expected_source_sections": expected_sections,
    }
    return rows, inputs


def source_request_case(bank, ordinal=0, count=1):
    """Reuse existing reviewed-body fixtures over the selected full population."""
    response_helper = helper().helper()
    auth_helper = response_helper.helper()
    auth_helper.fixture_helper = lambda: SimpleNamespace(fixture=lambda: source_population(bank, count))
    original_signed_case = auth_helper.signed_case

    def signed_case(owner, *, trust_mode="external_pinned_trust"):
        data = original_signed_case(owner, trust_mode=trust_mode)
        subject = data["preparation"]["subjects"][ordinal]
        for index, key in enumerate(data["registry"]["keys"]):
            tag = f"{bank}:{ordinal}:{index}"
            signer = Ed25519Signer.generate("did:example:cohort-source:" + tag)
            data["signers"][index] = signer
            key.update(key_id="fixture:cohort-source-key:" + tag,
                       principal_id="fixture:cohort-source-principal:" + tag,
                       signer_did=signer.did, scope_ids=[subject["scope_id"]],
                       public_key_hex=signer.public_key.public_bytes(
                           serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
            review = data["reviews"][index]
            review.update(review_id="fixture:cohort-source-review:" + tag,
                          key_id=key["key_id"], principal_id=key["principal_id"], subject=deepcopy(subject))
            review["interpretation"].update(reviewed_graph_sha256=subject["graph_sha256"],
                                            reviewed_ast_sha256=subject["ast_sha256"])
            for obligation, slot in zip(review["context_closure"]["obligations"], subject["context_slot_ids"], strict=True):
                obligation["slot_id"] = slot
        data.update(auth_helper.dependency_observations(data["preparation"]["dependency_manifests"][ordinal]))
        auth_helper.refresh_signatures(data)
        return data

    auth_helper.signed_case = signed_case
    response_helper.helper = lambda: auth_helper
    response_helper.record_arguments = lambda data: {
        **data["arguments"], "request_ordinal": ordinal,
        "expected_preparation_manifest_sha256": sha(wire(data["preparation"]["manifest"])),
    }
    original_declaration = response_helper.declaration

    def declaration(data, index=0, *, disposition="evidence_declared"):
        result = original_declaration(data, index, disposition=disposition)
        questions = [q for q in data["preparation"]["requests"][ordinal]["review_questions"]
                     if q["assessment_scope"] == "source_context_evidence_declaration"]
        for answer, question in zip(result["answers"], questions, strict=True):
            answer.update({key: question[key] for key in ("slot_id", "category", "kind")})
        return result

    response_helper.declaration = declaration
    data = response_helper.response_case(responses)
    data["typed_assessment"] = response_helper.assess(responses, data)
    data["response_inputs"] = deepcopy(response_helper.assessment_arguments(data))
    return data


def request_case(bank, ordinal=0, count=1, *, data=None):
    data = source_request_case(bank, ordinal, count) if data is None else data
    data = helper().signed_case(adjudication, data=data)
    subject = data["preparation"]["subjects"][ordinal]
    for index, key in enumerate(data["adjudication"]["registry"]["keys"]):
        tag = f"{bank}:{ordinal}:{index}"
        signer = Ed25519Signer.generate("did:example:cohort-adjudicator:" + tag)
        data["adjudication"]["signers"][index] = signer
        key.update(key_id="fixture:cohort-adjudication-key:" + tag,
                   principal_id="fixture:cohort-adjudicator:" + tag, signer_did=signer.did,
                   scope_ids=[subject["scope_id"]],
                   public_key_hex=signer.public_key.public_bytes(
                       serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
        data["adjudication"]["reviews"][index].update(
            review_id="fixture:cohort-adjudication-review:" + tag,
            key_id=key["key_id"], principal_id=key["principal_id"], subject=deepcopy(subject))
        data["adjudication"]["reviews"][index]["interpretation"].update(
            reviewed_graph_sha256=subject["graph_sha256"], reviewed_ast_sha256=subject["ast_sha256"])
    helper().resign(data)
    return data


def refresh_source_and_declaration(data, *, resign_source=True):
    """Rebuild declared fixtures after an explicit change, keeping exact pins."""
    if resign_source:
        helper().helper().helper().refresh_signatures(data)
    inputs = data["response_inputs"]
    inputs.update(expected_registry_sha256=sha(wire(data["registry"])),
                  expected_policy_sha256=sha(wire(data["policy"])),
                  expected_reviews_sha256=sha(wire(data["reviews"])),
                  evidence_artifacts=data["evidence_artifacts"])
    data["typed_assessment"] = responses.assess_legacy_source_responses(
        data["preparation"], data["registry"], data["policy"], data["reviews"], **inputs)
    choices = helper().decisions(data)
    body = helper().record(adjudication, data, choices)
    raw = wire(body)
    current = data["adjudication"]
    current.update(declaration=body, raw=raw, choices=choices,
                   evidence_artifacts={**data["evidence_artifacts"], helper().DECLARATION_ID: raw})
    for review in current["reviews"]:
        for obligation in review["context_closure"]["obligations"]:
            obligation["evidence_refs"] = [{"artifact_id": helper().DECLARATION_ID, "sha256": sha(raw)}]
    helper().resign(data)


def cohort_case(layout=(1, 1)):
    """Each bank has one shared source registry and every prepared request."""
    groups = []
    for bank_index, count in enumerate(layout):
        bank_id = f"fixture:bank:{bank_index}"
        group = [request_case(f"bank{bank_index}", ordinal, count) for ordinal in range(count)]
        registry = deepcopy(group[0]["registry"])
        registry["keys"] = [deepcopy(key) for data in group for key in data["registry"]["keys"]]
        policy = deepcopy(group[0]["policy"])
        policy["registry_sha256"] = sha(wire(registry))
        for data in group:
            data["registry"], data["policy"] = deepcopy(registry), deepcopy(policy)
            refresh_source_and_declaration(data)
        groups.append((bank_id, group))
    return groups


def request_ref(request):
    return {"record_cid": request["record_cid"], "sha256": sha(wire(request)), "schema": request["schema"]}


def cohort_inputs(groups):
    banks, expected = [], []
    for bank_id, group in groups:
        first = group[0]
        assert all(wire(data["preparation"]) == wire(first["preparation"])
                   and wire(data["registry"]) == wire(first["registry"])
                   and wire(data["policy"]) == wire(first["policy"]) for data in group)
        banks.append({"bank_id": bank_id, "preparation": first["preparation"],
            "source_registry": first["registry"], "source_policy": first["policy"],
            "requests": [{"typed_assessment": data["typed_assessment"],
                          "source_reviews": data["reviews"], "response_inputs": data["response_inputs"]}
                         for data in group]})
        expected.append({"bank_id": bank_id, "preparation_sha256": sha(wire(first["preparation"])),
            "registry_sha256": sha(wire(first["registry"])), "policy_sha256": sha(wire(first["policy"])),
            "requests": [{"request_ref": request_ref(data["preparation"]["requests"][ordinal]),
                          "typed_assessment_sha256": sha(wire(data["typed_assessment"])),
                          "source_reviews_sha256": sha(wire(data["reviews"]))}
                         for ordinal, data in enumerate(group)]})
    return banks, {"expected_population": expected, "expected_population_sha256": sha(wire(expected))}


def prepared(owner, groups):
    banks, arguments = cohort_inputs(groups)
    return owner.prepare_legacy_source_review_cohort(banks, **arguments), banks, arguments


def adjudication_inputs(groups):
    entries, hashes = [], []
    for bank_id, group in groups:
        for ordinal, data in enumerate(group):
            report = helper().assess(adjudication, data)
            inputs = helper().assessment_arguments(data)
            del inputs["response_inputs"], inputs["expected_typed_assessment_sha256"]
            entries.append({"bank_id": bank_id, "request_ordinal": ordinal, "assessment": report,
                "adjudication_registry": data["adjudication"]["registry"],
                "adjudication_policy": data["adjudication"]["policy"],
                "adjudication_reviews": data["adjudication"]["reviews"], "assessment_inputs": inputs})
            hashes.append(sha(wire(report)))
    return entries, hashes


def assess(owner, groups):
    cohort, banks, arguments = prepared(owner, groups)
    entries, hashes = adjudication_inputs(groups)
    kwargs = {**arguments, "expected_cohort_sha256": sha(wire(cohort)),
              "expected_adjudication_assessment_sha256s": hashes}
    report = owner.assess_legacy_source_cohort_adjudications(cohort, banks, entries, **kwargs)
    return report, (cohort, banks, entries), kwargs


def no_source_decision(report):
    assert report["selected_occurrence"] is None
    assert report["counts"]["source_decisions_applied"] == 0
    for flag in trust.FALSE_AUTHORITY:
        assert report[flag] is False
    assert report["cohort_human_independence_verified"] is False
    assert report["external_submission_inventory_exhaustive"] is False


def collide_adjudicator(target, other_source, attribute):
    current = target["adjudication"]
    key = current["registry"]["keys"][0]
    other_key = other_source["registry"]["keys"][0]
    if attribute == "principal":
        key["principal_id"] = other_key["principal_id"]
        current["reviews"][0]["principal_id"] = key["principal_id"]
    elif attribute == "did":
        signer = Ed25519Signer.generate(other_key["signer_did"])
        current["signers"][0] = signer
        key.update(signer_did=signer.did, public_key_hex=signer.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
    else:
        current["signers"][0] = Ed25519Signer(key["signer_did"], other_source["signers"][0].private_key)
        key["public_key_hex"] = other_key["public_key_hex"]
    helper().resign(target)


def test_clean_two_bank_cohort_replays_all_requests_and_applies_nothing(owner):
    groups = cohort_case()
    before = wire(cohort_inputs(groups)[1])
    cohort, banks, arguments = prepared(owner, groups)
    assert cohort["complete_under_expected_population"] is True
    assert cohort["counts"]["banks"] == cohort["counts"]["requests"] == 2
    assert cohort["counts"]["reviews"] == 4
    assert cohort["counts"]["unknown_key_reviews"] == 0
    assert owner.validate_legacy_source_review_cohort(cohort, banks, **arguments) == cohort
    report, inputs, kwargs = assess(owner, groups)
    assert report["counts"]["requests"] == report["counts"]["eligible_requests"] == 2
    assert report["counts"]["excluded_requests"] == 0
    assert all(row["original_authority_prerequisites_satisfied"] is True
               and row["cohort_authority_prerequisites_satisfied"] is True
               and row["exclusion_matches"] == [] for row in report["request_results"])
    assert [row["adjudication_assessment_sha256"] for row in report["request_results"]] == kwargs[
        "expected_adjudication_assessment_sha256s"]
    assert owner.validate_legacy_source_cohort_adjudications(report, *inputs, **kwargs) == report
    assert before == wire(cohort_inputs(groups)[1])
    no_source_decision(report)


@pytest.mark.parametrize("layout", [(1, 1), (2,)])
@pytest.mark.parametrize("attribute", ["principal", "did", "public_key"])
def test_other_request_or_bank_source_reviewer_cannot_adjudicate(owner, layout, attribute):
    groups = cohort_case(layout)
    all_data = [data for _, group in groups for data in group]
    other_source, target = all_data
    collide_adjudicator(target, other_source, attribute)
    report, _, _ = assess(owner, groups)
    target_result = report["request_results"][1]
    assert target_result["original_authority_prerequisites_satisfied"] is True
    assert target_result["cohort_authority_prerequisites_satisfied"] is False
    assert target_result["exclusion_matches"] and target_result["blockers"]
    assert report["counts"]["excluded_requests"] == 1
    no_source_decision(report)


@pytest.mark.parametrize("damage", ["rejected_signature", "malformed_typed", "mismatched_claim_identity"])
def test_rejected_or_malformed_source_claims_still_exclude_known_participants(owner, damage):
    groups = cohort_case()
    other_source, target = groups[0][1][0], groups[1][1][0]
    if damage == "rejected_signature":
        signature = other_source["reviews"][0]["signature"]
        other_source["reviews"][0]["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    elif damage == "malformed_typed":
        binding = other_source["response_bindings"][0]
        other_source["evidence_artifacts"][binding["artifact_id"]] = b"{}"
    else:
        other_source["reviews"][0]["principal_id"] = "fixture:mismatched-source-claimant"
        helper().helper().helper().refresh_signatures(other_source)
    refresh_source_and_declaration(other_source, resign_source=False)
    assert other_source["typed_assessment"]["counts"]["authenticated_typed_responses"] == 1
    collide_adjudicator(target, other_source, "principal")
    cohort, _, _ = prepared(owner, groups)
    assert cohort["counts"]["reviews"] == 4
    inventory = cohort["banks"][0]["requests"][0]["reviewer_inventory"]
    assert len(inventory) == 2
    assert inventory[0]["authenticated_typed_content"] is False
    assert other_source["registry"]["keys"][0]["principal_id"] in cohort["excluded_principal_ids"]
    assert other_source["reviews"][0]["principal_id"] in cohort["excluded_principal_ids"]
    report, _, _ = assess(owner, groups)
    assert report["request_results"][1]["original_authority_prerequisites_satisfied"] is True
    assert report["request_results"][1]["cohort_authority_prerequisites_satisfied"] is False
    assert report["request_results"][1]["exclusion_matches"]
    no_source_decision(report)


def test_unknown_source_key_prevents_a_clean_independence_claim(owner):
    groups = cohort_case()
    other_source = groups[0][1][0]
    other_source["reviews"][0]["key_id"] = "fixture:unavailable-source-key"
    helper().helper().helper().refresh_signatures(other_source)
    refresh_source_and_declaration(other_source, resign_source=False)
    cohort, _, _ = prepared(owner, groups)
    assert cohort["counts"]["unknown_key_reviews"] == 1
    report, _, _ = assess(owner, groups)
    assert report["request_results"][1]["original_authority_prerequisites_satisfied"] is True
    assert report["request_results"][1]["cohort_authority_prerequisites_satisfied"] is False
    assert report["request_results"][1]["blockers"]
    no_source_decision(report)


@pytest.mark.parametrize("damage", ["drop_bank", "duplicate_bank", "bank_order", "drop_request",
    "duplicate_request", "request_order", "wrong_digest", "bool_ordinal", "extra_field", "typed_flag_alias"])
def test_preparation_rejects_filtered_reordered_or_malformed_population(owner, damage):
    groups = cohort_case((2, 1))
    banks, arguments = cohort_inputs(groups)
    banks = deepcopy(banks)
    if damage == "drop_bank":
        banks.pop()
    elif damage == "duplicate_bank":
        banks[1] = deepcopy(banks[0])
    elif damage == "bank_order":
        banks.reverse()
    elif damage == "drop_request":
        banks[0]["requests"].pop()
    elif damage == "duplicate_request":
        banks[0]["requests"][1] = deepcopy(banks[0]["requests"][0])
    elif damage == "request_order":
        banks[0]["requests"].reverse()
    elif damage == "wrong_digest":
        arguments["expected_population_sha256"] = "0" * 64
    elif damage == "bool_ordinal":
        banks[0]["requests"][0]["response_inputs"]["request_ordinal"] = False
    elif damage == "extra_field":
        banks[0]["filtered_to_passes"] = True
    else:
        banks[0]["requests"][0]["typed_assessment"]["admitted"] = 0
        arguments["expected_population"][0]["requests"][0]["typed_assessment_sha256"] = sha(
            wire(banks[0]["requests"][0]["typed_assessment"]))
        arguments["expected_population_sha256"] = sha(wire(arguments["expected_population"]))
    with pytest.raises(ValueError):
        owner.prepare_legacy_source_review_cohort(banks, **arguments)


def test_duplicate_request_identity_cannot_be_rebranded_as_another_bank(owner):
    groups = cohort_case((1,))
    groups.append(("fixture:different-bank-label", groups[0][1]))
    banks, arguments = cohort_inputs(groups)
    with pytest.raises(ValueError):
        owner.prepare_legacy_source_review_cohort(banks, **arguments)


def test_smaller_expected_list_does_not_hide_prepared_requests(owner):
    groups = cohort_case((2,))
    banks, arguments = cohort_inputs(groups)
    banks[0]["requests"].pop()
    arguments["expected_population"][0]["requests"].pop()
    arguments["expected_population_sha256"] = sha(wire(arguments["expected_population"]))
    with pytest.raises(ValueError):
        owner.prepare_legacy_source_review_cohort(banks, **arguments)


@pytest.mark.parametrize("damage", ["drop", "duplicate", "order", "hash_population", "forged_report",
                                     "bool_flag_alias", "bool_ordinal", "cohort_hash", "extra_field"])
def test_batch_requires_complete_pinned_original_assessments_and_exact_replay(owner, damage):
    groups = cohort_case()
    cohort, banks, arguments = prepared(owner, groups)
    entries, hashes = adjudication_inputs(groups)
    kwargs = {**arguments, "expected_cohort_sha256": sha(wire(cohort)),
              "expected_adjudication_assessment_sha256s": hashes}
    if damage == "drop":
        entries.pop()
    elif damage == "duplicate":
        entries[1] = deepcopy(entries[0])
    elif damage == "order":
        entries.reverse()
    elif damage == "hash_population":
        kwargs["expected_adjudication_assessment_sha256s"].pop()
    elif damage in {"forged_report", "bool_flag_alias"}:
        if damage == "forged_report":
            entries[0]["assessment"]["authority_prerequisites_satisfied_under_selected_trust"] = False
        else:
            entries[0]["assessment"]["admitted"] = 0
        kwargs["expected_adjudication_assessment_sha256s"][0] = sha(wire(entries[0]["assessment"]))
    elif damage == "bool_ordinal":
        entries[0]["request_ordinal"] = False
    elif damage == "cohort_hash":
        kwargs["expected_cohort_sha256"] = "0" * 64
    else:
        entries[0]["accepted_by_organizer"] = True
    with pytest.raises(ValueError):
        owner.assess_legacy_source_cohort_adjudications(cohort, banks, entries, **kwargs)


@pytest.mark.parametrize("cap", ["MAX_BANKS", "MAX_REQUESTS", "MAX_REVIEWS", "MAX_REPLAY_BYTES"])
def test_population_bounds_refuse_instead_of_truncating(owner, monkeypatch, cap):
    groups = cohort_case()
    banks, arguments = cohort_inputs(groups)
    monkeypatch.setattr(owner, cap, 1)
    with pytest.raises(ValueError):
        owner.prepare_legacy_source_review_cohort(banks, **arguments)


@pytest.mark.parametrize("target", ["cohort", "assessment"])
def test_validators_reject_boolean_integer_aliases(owner, target):
    groups = cohort_case()
    if target == "cohort":
        cohort, banks, arguments = prepared(owner, groups)
        cohort["admitted"] = 0
        with pytest.raises(ValueError):
            owner.validate_legacy_source_review_cohort(cohort, banks, **arguments)
    else:
        report, inputs, kwargs = assess(owner, groups)
        report["admitted"] = 0
        with pytest.raises(ValueError):
            owner.validate_legacy_source_cohort_adjudications(report, *inputs, **kwargs)
