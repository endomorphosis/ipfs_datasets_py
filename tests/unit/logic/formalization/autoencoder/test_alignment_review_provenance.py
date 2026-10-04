"""Disposable fixture keys exercise transport checks, never genuine reviews."""
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_review_provenance as subject

_spec = importlib.util.spec_from_file_location("_provenance_handoff_fixtures", Path(__file__).with_name(
    "test_alignment_relation_mask_handoff.py"))
handoff_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handoff_fixtures)


def _private_key(key_id):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    seed = bytes(range(32)) if key_id == "fixture-reviewer-key" else bytes(range(32, 64))
    return Ed25519PrivateKey.from_private_bytes(seed)


def _refresh(value, *, resign=False):
    registry, policy, bundle = value["registry"], value["policy"], value["attestations"]
    subject._seal(registry)
    subject._seal(policy)
    for row in bundle["rows"]:
        if resign:
            row["signature_hex"] = _private_key(row["payload"]["key_id"]).sign(subject.provenance_signing_bytes(row["payload"])).hex()
        subject._seal(row)
    subject._seal(bundle)
    expected = value["expected_bindings"]
    for key in ("registry", "policy", "attestations"):
        expected[key + "_sha256"] = subject._digest(value[key])
    return value


def provenance_fixture(n=2):
    """Return closed invented inputs; exactly two key initializations and 2N+2N² signatures.

    These fixed 32-byte seeds are disposable test material. They represent no
    person, organizer, independently reviewed source or authentic semantic label.
    No private key or seed is included in the returned package.
    """
    from cryptography.hazmat.primitives import serialization

    declaration, snapshot, mask_policy, handoff_pins = handoff_fixtures.synthetic(n=n)
    receipt = subject.handoffs.compile_train_relation_masks(declaration, snapshot, mask_policy, expected_bindings=handoff_pins)
    envelope = {"snapshot": snapshot, "policy": mask_policy, "receipt": receipt}
    keys = {"fixture-reviewer-key": _private_key("fixture-reviewer-key"),
            "fixture-adjudicator-key": _private_key("fixture-adjudicator-key")}
    registry = subject._seal({"schema": subject.REGISTRY_SCHEMA, "mode": subject.SYNTHETIC_REGISTRY,
        "process_id": "invented-engineering-process", "generation": 1, "revocation_generation": 0,
        "keys": [{"key_id": identity, "public_key_hex": key.public_key().public_bytes(serialization.Encoding.Raw,
            serialization.PublicFormat.Raw).hex(), "principal_id": "invented-" + role, "role": role,
            "action": subject.ACTION, "audience": subject.AUDIENCE, "scope": deepcopy(receipt["declared_semantic_scope"]),
            "valid_from_utc": "2026-01-01T00:00:00Z", "valid_until_utc": "2027-01-01T00:00:00Z", "revoked_at_utc": None}
            for identity, role, key in (("fixture-reviewer-key", "reviewer", keys["fixture-reviewer-key"]),
                                        ("fixture-adjudicator-key", "adjudicator", keys["fixture-adjudicator-key"]))]})
    policy = subject._seal({"schema": subject.POLICY_SCHEMA, "mode": subject.SYNTHETIC,
        "registry_sha256": subject._digest(registry), "registry_generation": registry["generation"],
        "revocation_generation": registry["revocation_generation"], "process_id": registry["process_id"],
        "action": subject.ACTION, "audience": subject.AUDIENCE, "evaluation_time_utc": "2026-10-04T12:00:00Z"})
    rows = []
    for index, (association, slot) in enumerate(subject._slots(declaration, envelope)[1].items()):
        kind = association[0]
        role = subject.KINDS[kind]
        identity = "fixture-" + role + "-key"
        body = {"schema": subject.PAYLOAD_SCHEMA, "attestation_id": "invented-attestation-" + str(index),
            "kind": kind, "key_id": identity, "principal_id": "invented-" + role, "role": role,
            "action": subject.ACTION, "audience": subject.AUDIENCE, "process_id": registry["process_id"],
            "registry_sha256": subject._digest(registry), "policy_sha256": subject._digest(policy),
            "registry_generation": registry["generation"], "revocation_generation": registry["revocation_generation"],
            "declaration_sha256": subject._digest(declaration), "handoff_sha256": subject._digest(envelope),
            "issued_at_utc": "2026-10-04T11:00:00Z", "expires_at_utc": "2026-10-04T13:00:00Z",
            "subject": deepcopy(slot["subject"]), "scope": deepcopy(receipt["declared_semantic_scope"]),
            "reference_sha256": slot["reference_sha256"]}
        rows.append(subject._seal({"schema": subject.ATTESTATION_SCHEMA, "payload": body,
            "signature_hex": keys[identity].sign(subject.provenance_signing_bytes(body)).hex()}))
    bundle = subject._seal({"schema": subject.BUNDLE_SCHEMA, "declaration_sha256": subject._digest(declaration),
        "handoff_sha256": subject._digest(envelope), "registry_sha256": subject._digest(registry),
        "policy_sha256": subject._digest(policy), "rows": rows})
    expected = {"declaration_sha256": subject._digest(declaration), "declaration_roles": handoff_pins["declaration_roles"],
        "handoff_sha256": subject._digest(envelope), "handoff_bindings": handoff_pins,
        "registry_sha256": subject._digest(registry), "policy_sha256": subject._digest(policy), "attestations_sha256": subject._digest(bundle)}
    return subject._detach({"declaration": declaration, "handoff_envelope": envelope, "registry": registry,
        "policy": policy, "attestations": bundle, "expected_bindings": expected,
        "fixture_activity": {"deterministic_private_key_objects_initialized": 2, "random_key_generation_calls": 0,
                             "signatures_created": len(rows)}})


def verify(value):
    return subject.verify_train_review_provenance(value["declaration"], value["handoff_envelope"], value["registry"],
        value["policy"], value["attestations"], expected_bindings=value["expected_bindings"])


def test_provenance_disposable_fixture_signatures_are_real_math_without_human_or_semantic_authority():
    value = provenance_fixture()
    original = deepcopy(value)
    result = verify(value)
    assert result["attestation_count"] == result["signature_checks_executed"] == result["valid_signature_count"] == 12
    assert result["declared_fixture_scope_permitted_count"] == 12 and result["denied_attestation_count"] == 0
    assert len(result["endpoint_signature_ledger"]) == 4 and len(result["pair_signature_ledger"]) == 8
    assert result["train_row_count"] == 2 and result["pair_count"] == 4
    assert all(result[key] is False for key in subject.FALSE)
    assert result["masks"] == dict.fromkeys(subject.MASKS, 0)
    assert all(result[key] == 0 and type(result[key]) is int for key in subject.handoffs.COUNTERS)
    for key in ("objective_positive_mask", "objective_permitted_negative_mask", "admitted_positive_mask", "admitted_permitted_negative_mask"):
        assert result[key] == [[False] * 2 for _ in range(2)]
    assert result == verify(value) and value == original
    result["attestation_rows"][0]["subject"]["left_endpoint"]["id"] = "mutated"
    result["expected_bindings"]["registry_sha256"] = "f" * 64
    assert value == original
    assert verify(value)["attestation_rows"][0]["subject"]["left_endpoint"]["id"] != "mutated"


def test_provenance_unavailable_preparer_retains_complete_16_train_256_pair_ledger_without_crypto(monkeypatch):
    declaration = handoff_fixtures.fixtures.declaration(n=16)
    prepared = subject.handoffs.prepare_unavailable_relation_handoff(declaration,
        expected_declaration_bindings=handoff_fixtures.fixtures.pins(declaration))
    envelope = {"snapshot": prepared["snapshot"], "policy": prepared["policy"], "receipt": prepared["validation"]}
    monkeypatch.setattr(subject, "_verify_signature", lambda *args: pytest.fail("unavailable must not execute crypto"))
    result = subject.prepare_unavailable_review_provenance(declaration, envelope,
        expected_declaration_bindings=handoff_fixtures.fixtures.pins(declaration), expected_handoff_bindings=prepared["expected_bindings"])
    assert set(result) == {"registry", "policy", "attestations", "expected_bindings", "verification"}
    receipt = result["verification"]
    assert receipt["train_row_count"] == 16 and receipt["pair_count"] == 256
    assert len(receipt["endpoint_signature_ledger"]) == 32 and len(receipt["pair_signature_ledger"]) == 512
    assert receipt["missing_attestation_slot_count"] == 544
    assert receipt["signature_checks_executed"] == receipt["valid_signature_count"] == 0
    assert receipt["status"] == "unavailable_review_process"
    assert all(receipt[key] is False for key in subject.FALSE)


def test_provenance_domain_is_fixed_and_payload_is_canonical_utf8():
    body = {"z": "é", "a": 1}
    assert subject.provenance_signing_bytes(body) == subject.DOMAIN + b'{"a":1,"z":"\xc3\xa9"}'
    assert subject.provenance_signing_bytes(body) == subject.provenance_signing_bytes({"a": 1, "z": "é"})


def test_provenance_one_signature_bit_changes_math_but_preserves_every_endpoint_and_pair():
    value = provenance_fixture()
    row = value["attestations"]["rows"][0]
    bits = bytearray.fromhex(row["signature_hex"])
    bits[0] ^= 1
    row["signature_hex"] = bits.hex()
    _refresh(value)
    result = verify(value)
    assert result["valid_signature_count"] == result["declared_fixture_scope_permitted_count"] == 11
    assert result["signature_checks_executed"] == 12 and result["denied_attestation_count"] == 1
    assert result["attestation_rows"][0]["signature_status"] == "invalid"
    assert result["missing_attestation_slot_count"] == 0


@pytest.mark.parametrize("field", ["source_sha256", "context_sha256", "input_sha256", "formal_view_sha256"])
def test_provenance_exact_endpoint_hashes_cannot_be_swapped_even_under_a_valid_fixture_signature(field):
    value = provenance_fixture()
    value["attestations"]["rows"][0]["payload"]["subject"]["left_endpoint"][field] = "f" * 64
    _refresh(value, resign=True)
    row = verify(value)["attestation_rows"][0]
    assert row["signature_valid"] is True and row["declared_fixture_scope_permitted"] is False
    assert "exact_endpoint_binding_differs" in row["denial_reasons"]


@pytest.mark.parametrize("field", ["declaration_sha256", "handoff_sha256", "registry_sha256", "policy_sha256", "reference_sha256"])
def test_provenance_valid_signature_over_foreign_generation_or_reference_is_denied(field):
    value = provenance_fixture()
    value["attestations"]["rows"][0]["payload"][field] = "f" * 64
    _refresh(value, resign=True)
    row = verify(value)["attestation_rows"][0]
    assert row["signature_valid"] is True and row["declared_fixture_scope_permitted"] is False


@pytest.mark.parametrize("field", ["action", "audience", "process_id", "principal_id", "role"])
def test_provenance_valid_signature_does_not_override_declared_principal_role_or_policy_scope(field):
    value = provenance_fixture()
    value["attestations"]["rows"][0]["payload"][field] = "foreign-declaration"
    _refresh(value, resign=True)
    row = verify(value)["attestation_rows"][0]
    assert row["signature_valid"] is True and row["declared_fixture_scope_permitted"] is False


def test_provenance_scope_family_profile_and_assumptions_are_bound_without_semantic_claims():
    for field, replacement in (("source_family_id", "another-family"), ("target_semantic_profile_sha256", "f" * 64),
                               ("assumptions_sha256", "e" * 64)):
        value = provenance_fixture()
        value["attestations"]["rows"][0]["payload"]["scope"][field] = replacement
        _refresh(value, resign=True)
        row = verify(value)["attestation_rows"][0]
        assert row["signature_valid"] is True and "signed_semantic_scope_differs" in row["denial_reasons"]


def test_provenance_unknown_registry_key_denies_without_attempting_signature_math():
    value = provenance_fixture()
    value["attestations"]["rows"][0]["payload"]["key_id"] = "unknown-key"
    _refresh(value)
    result = verify(value)
    assert result["signature_checks_executed"] == 11 and result["denied_attestation_count"] == 1
    assert result["attestation_rows"][0]["signature_status"] == "not_attempted_unknown_key"


def test_provenance_raw_key_substitution_is_checked_by_real_signature_math():
    value = provenance_fixture()
    value["registry"]["keys"][0]["public_key_hex"] = "ab" * 32
    _refresh(value)
    result = verify(value)
    assert result["attestation_rows"][0]["signature_status"] == "invalid"
    assert result["actual_fit_authorized"] is False


@pytest.mark.parametrize("field", ["registry_generation", "revocation_generation"])
def test_provenance_stale_policy_generation_is_retained_denied_even_after_full_external_reselection(field):
    value = provenance_fixture()
    value["policy"][field] += 1
    _refresh(value)
    result = verify(value)
    assert result["valid_signature_count"] == 12 and result["declared_fixture_scope_permitted_count"] == 0
    assert "policy_" + field + "_differs" in result["common_denial_reasons"]


@pytest.mark.parametrize("issued,expires,permitted", [
    ("2026-10-04T12:00:00Z", "2026-10-04T13:00:00Z", True),
    ("2026-10-04T12:00:01Z", "2026-10-04T13:00:00Z", False),
    ("2026-10-04T11:00:00Z", "2026-10-04T12:00:00Z", False),
    ("2026-10-04T11:00:00Z", "2026-10-04T12:00:01Z", True)])
def test_provenance_selected_time_uses_inclusive_issue_and_exclusive_expiry(issued, expires, permitted):
    value = provenance_fixture()
    value["attestations"]["rows"][0]["payload"].update(issued_at_utc=issued, expires_at_utc=expires)
    _refresh(value, resign=True)
    row = verify(value)["attestation_rows"][0]
    assert row["signature_valid"] is True and row["declared_fixture_scope_permitted"] is permitted


@pytest.mark.parametrize("field,time,denied", [
    ("valid_from_utc", "2026-10-04T11:00:00Z", False), ("valid_from_utc", "2026-10-04T11:00:01Z", True),
    ("valid_until_utc", "2026-10-04T12:00:00Z", True), ("valid_until_utc", "2026-10-04T12:00:01Z", False),
    ("revoked_at_utc", "2026-10-04T12:00:00Z", True), ("revoked_at_utc", "2026-10-04T12:00:01Z", False)])
def test_provenance_key_validity_and_offline_revocation_use_same_selected_time(field, time, denied):
    value = provenance_fixture()
    value["registry"]["keys"][0][field] = time
    subject._seal(value["registry"])
    value["policy"]["registry_sha256"] = subject._digest(value["registry"])
    subject._seal(value["policy"])
    value["attestations"].update(registry_sha256=subject._digest(value["registry"]), policy_sha256=subject._digest(value["policy"]))
    for entry in value["attestations"]["rows"]:
        entry["payload"].update(registry_sha256=subject._digest(value["registry"]), policy_sha256=subject._digest(value["policy"]))
    _refresh(value, resign=True)
    row = verify(value)["attestation_rows"][0]
    assert row["signature_valid"] is True and row["declared_fixture_scope_permitted"] is not denied


def test_provenance_reviewer_key_cannot_claim_adjudicator_role_even_with_valid_signature():
    value = provenance_fixture()
    row = next(row for row in value["attestations"]["rows"] if row["payload"]["kind"] == "pair_adjudication")
    row["payload"].update(key_id="fixture-reviewer-key", principal_id="invented-reviewer", role="reviewer")
    _refresh(value, resign=True)
    result = next(row for row in verify(value)["attestation_rows"] if row["kind"] == "pair_adjudication")
    assert result["signature_valid"] is True and "kind_role_mapping_differs" in result["denial_reasons"]


def test_provenance_partial_and_reordered_signatures_keep_complete_ordered_slots_without_inference():
    value = provenance_fixture()
    value["attestations"]["rows"] = list(reversed(value["attestations"]["rows"][:2]))
    _refresh(value)
    result = verify(value)
    assert result["valid_signature_count"] == 2 and result["missing_attestation_slot_count"] == 10
    assert len(result["endpoint_signature_ledger"]) == 4 and len(result["pair_signature_ledger"]) == 8
    assert result["pair_signature_ledger"][0]["signature_valid"] is False
    assert result["objective_positive_mask"] == [[False] * 2 for _ in range(2)]


@pytest.mark.parametrize("kind", ["id", "association"])
def test_provenance_duplicate_ids_or_slot_credit_reject_even_with_other_keys(kind):
    value = provenance_fixture()
    if kind == "id":
        value["attestations"]["rows"][1]["payload"]["attestation_id"] = value["attestations"]["rows"][0]["payload"]["attestation_id"]
    else:
        extra = deepcopy(value["attestations"]["rows"][0])
        extra["payload"].update(attestation_id="another-id", key_id="fixture-adjudicator-key")
        value["attestations"]["rows"].append(extra)
    _refresh(value)
    with pytest.raises(ValueError, match="duplicate attestation"):
        verify(value)


@pytest.mark.parametrize("name", ["registry", "policy", "attestations"])
def test_provenance_resealed_generations_cannot_replace_selected_external_pins(name):
    value = provenance_fixture()
    expected = deepcopy(value["expected_bindings"])
    if name == "registry":
        value[name]["revocation_generation"] = 1
    elif name == "policy":
        value[name]["evaluation_time_utc"] = "2026-10-04T12:00:01Z"
    else:
        value[name]["rows"] = value[name]["rows"][:-1]
    _refresh(value)
    value["expected_bindings"] = expected
    with pytest.raises(ValueError, match="selected .* generation differs"):
        verify(value)


@pytest.mark.parametrize("mutation", ["policy_unavailable", "registry_unavailable", "real_mode", "self_key", "resolver", "algorithm", "generation_bool", "invalid_signature", "invalid_key", "date_alias", "scope_extra", "kind_list", "singleton_pair", "nonfinite", "nonutf8"])
def test_provenance_closed_types_modes_algorithms_keys_and_dates_reject(mutation):
    value = provenance_fixture()
    if mutation == "policy_unavailable":
        value["policy"]["mode"] = subject.UNAVAILABLE
    elif mutation == "registry_unavailable":
        value["registry"]["mode"] = subject.UNAVAILABLE_REGISTRY
    elif mutation == "real_mode":
        value["policy"]["mode"] = "authenticated_human_review/v1"
    elif mutation == "self_key":
        value["attestations"]["rows"][0]["payload"]["public_key_hex"] = "ab" * 32
    elif mutation == "resolver":
        value["registry"]["key_resolver"] = "caller-supplied"
    elif mutation == "algorithm":
        value["attestations"]["rows"][0]["algorithm"] = "EdDSA"
    elif mutation == "generation_bool":
        value["registry"]["generation"] = True
    elif mutation == "invalid_signature":
        value["attestations"]["rows"][0]["signature_hex"] = "ff"
    elif mutation == "invalid_key":
        value["registry"]["keys"][0]["public_key_hex"] = "-----BEGIN PUBLIC KEY-----"
    elif mutation == "date_alias":
        value["policy"]["evaluation_time_utc"] = "2026-10-04T12:00:00+00:00"
    elif mutation == "scope_extra":
        value["registry"]["keys"][0]["scope"]["authenticated"] = True
    elif mutation == "kind_list":
        value["attestations"]["rows"][0]["payload"]["kind"] = []
    elif mutation == "singleton_pair":
        value["attestations"]["rows"][0]["payload"]["subject"]["right_endpoint"] = deepcopy(value["attestations"]["rows"][0]["payload"]["subject"]["left_endpoint"])
    elif mutation == "nonfinite":
        value["policy"]["evaluation_time_utc"] = float("nan")
    else:
        value["registry"]["process_id"] = "\ud800"
    with pytest.raises(ValueError):
        _refresh(value)
        verify(value)


@pytest.mark.parametrize("field", ["registry_generation", "revocation_generation"])
def test_provenance_signed_generations_reject_boolean_aliases(field):
    value = provenance_fixture()
    value["attestations"]["rows"][0]["payload"][field] = True
    _refresh(value)
    with pytest.raises(ValueError, match="integer"):
        verify(value)


def test_provenance_duplicate_registry_key_material_cannot_supply_multiple_principal_credit():
    value = provenance_fixture()
    value["registry"]["keys"][1]["public_key_hex"] = value["registry"]["keys"][0]["public_key_hex"]
    _refresh(value)
    with pytest.raises(ValueError, match="duplicate registry public key"):
        verify(value)


def test_provenance_backend_unavailability_is_never_signature_valid_or_declared_scope_permitted(monkeypatch):
    value = provenance_fixture()
    monkeypatch.setattr(subject, "_verify_signature", lambda *args: ("backend_unavailable", False))
    result = verify(value)
    assert result["signature_checks_executed"] == result["valid_signature_count"] == result["declared_fixture_scope_permitted_count"] == 0
    assert result["denied_attestation_count"] == 12
    assert all(row["signature_status"] == "backend_unavailable" for row in result["attestation_rows"])


def test_provenance_unsupported_ed25519_provider_is_retained_as_backend_unavailable(monkeypatch):
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    value = provenance_fixture()

    def unavailable(*args):
        raise UnsupportedAlgorithm("synthetic unsupported provider")

    monkeypatch.setattr(Ed25519PublicKey, "from_public_bytes", unavailable)
    result = verify(value)
    assert result["signature_checks_executed"] == result["valid_signature_count"] == 0
    assert result["denied_attestation_count"] == 12
    assert all(row["signature_status"] == "backend_unavailable" for row in result["attestation_rows"])


def test_provenance_multiple_keys_for_one_declared_principal_never_count_as_independent_people():
    value = provenance_fixture()
    for key in value["registry"]["keys"]:
        key["principal_id"] = "same-invented-principal"
    subject._seal(value["registry"])
    value["policy"]["registry_sha256"] = subject._digest(value["registry"])
    subject._seal(value["policy"])
    value["attestations"].update(registry_sha256=subject._digest(value["registry"]), policy_sha256=subject._digest(value["policy"]))
    for entry in value["attestations"]["rows"]:
        entry["payload"].update(principal_id="same-invented-principal", registry_sha256=subject._digest(value["registry"]),
                                policy_sha256=subject._digest(value["policy"]))
    _refresh(value, resign=True)
    result = verify(value)
    assert result["valid_signature_count"] == 12 and result["declared_fixture_scope_permitted_count"] == 12
    assert result["declared_attesting_principal_ids"] == ["same-invented-principal"]
    assert result["declared_attesting_principal_count"] == result["declared_scope_permitted_principal_count"] == 1
    assert result["human_reviews_authenticated"] == result["independent_reviews_authenticated"] == 0


@pytest.mark.parametrize("mutation", ["fit", "identity", "mask", "count", "bool_alias", "extra"])
def test_provenance_saved_receipt_full_replay_prevents_resealed_authority_or_count_promotion(mutation):
    value = provenance_fixture()
    receipt = verify(value)
    checked = subject.validate_train_review_provenance(receipt, value["declaration"], value["handoff_envelope"],
        value["registry"], value["policy"], value["attestations"], expected_bindings=value["expected_bindings"])
    assert all(checked[key] is False for key in subject.FALSE)
    if mutation == "fit":
        receipt["actual_fit_authorized"] = True
    elif mutation == "identity":
        receipt["reviewer_identity_authenticated"] = True
    elif mutation == "mask":
        receipt["masks"]["contrastive_supervision"] = 1
    elif mutation == "count":
        receipt["valid_signature_count"] = 100
    elif mutation == "bool_alias":
        receipt["model_calls"] = False
    else:
        receipt["approved"] = True
    subject._seal(receipt)
    with pytest.raises(ValueError, match="exact replay"):
        subject.validate_train_review_provenance(receipt, value["declaration"], value["handoff_envelope"],
            value["registry"], value["policy"], value["attestations"], expected_bindings=value["expected_bindings"])


def test_provenance_original_handoff_and_declaration_pins_cannot_be_forged_or_cross_swapped():
    value = provenance_fixture()
    value["handoff_envelope"]["receipt"]["actual_fit_authorized"] = True
    subject._seal(value["handoff_envelope"]["receipt"])
    value["expected_bindings"]["handoff_sha256"] = subject._digest(value["handoff_envelope"])
    with pytest.raises(ValueError, match="exact replay"):
        verify(value)
    value = provenance_fixture()
    value["expected_bindings"]["declaration_roles"]["pair_ledger"]["value_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        verify(value)


def test_provenance_signature_and_aggregate_input_caps_reject_without_crypto(monkeypatch):
    value = provenance_fixture()
    monkeypatch.setattr(subject, "MAX_SIGNATURES", 1)
    with pytest.raises(ValueError, match="bounded detached signatures"):
        verify(value)
    monkeypatch.setattr(subject, "MAX_SIGNATURES", 1024)
    monkeypatch.setattr(subject, "MAX_BYTES", 1000)
    with pytest.raises(ValueError, match="byte bound"):
        verify(value)


def test_provenance_inert_import_and_unavailable_replay_need_no_crypto_io_models_or_live_clock(tmp_path):
    declaration = handoff_fixtures.fixtures.declaration()
    prepared = subject.handoffs.prepare_unavailable_relation_handoff(declaration,
        expected_declaration_bindings=handoff_fixtures.fixtures.pins(declaration))
    envelope = {"snapshot": prepared["snapshot"], "policy": prepared["policy"], "receipt": prepared["validation"]}
    payload = json.dumps({"declaration": declaration, "envelope": envelope, "roles": handoff_fixtures.fixtures.pins(declaration),
                          "handoff": prepared["expected_bindings"]})
    root = Path(__file__).resolve().parents[5]
    code = '''
import importlib.abc,json,sys,types
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root))
for name,relative in [('ipfs_datasets_py','ipfs_datasets_py'),('ipfs_datasets_py.logic','ipfs_datasets_py/logic'),('ipfs_datasets_py.logic.formalization','ipfs_datasets_py/logic/formalization'),('ipfs_datasets_py.logic.formalization.autoencoder','ipfs_datasets_py/logic/formalization/autoencoder')]:
 m=types.ModuleType(name);m.__path__=[str(root/relative)];m.__package__=name;sys.modules[name]=m
blocked={'cryptography','torch','numpy','scipy','transformers','sentence_transformers','spacy','lean','z3','cvc5'}
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in blocked: raise RuntimeError('optional stack import')
sys.meta_path.insert(0,Guard())
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_review_provenance as subject
request=json.loads(sys.stdin.read())
def deny(event,args):
 if event in {'open','os.listdir','os.scandir','subprocess.Popen','socket.__new__'}: raise RuntimeError('I/O during provenance verification')
sys.addaudithook(deny)
prepared=subject.prepare_unavailable_review_provenance(request['declaration'],request['envelope'],expected_declaration_bindings=request['roles'],expected_handoff_bindings=request['handoff'])
receipt=prepared['verification']
subject.validate_train_review_provenance(receipt,request['declaration'],request['envelope'],prepared['registry'],prepared['policy'],prepared['attestations'],expected_bindings=prepared['expected_bindings'])
assert not blocked.intersection(sys.modules)
print(json.dumps({'signature_checks':receipt['signature_checks_executed'],'human_auth':receipt['human_reviews_authenticated']}))
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)], input=payload, text=True,
                            capture_output=True, cwd=tmp_path, timeout=10, check=True)
    assert json.loads(result.stdout) == {"signature_checks": 0, "human_auth": 0}
