"""Golden compatibility contract for the mutable legacy Security IR v1."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from collections.abc import Mapping, MutableMapping, MutableSequence
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange import default_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir import cid as cid_module
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import canonicalize_ir
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    DEFAULT_THREAT_MODEL_ASSUMPTIONS,
    SecurityModelIR,
    claim_domains,
    validate_domain_coverage,
    validate_ir,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_receipt import (
    ProofReceipt,
    validate_proof_receipt,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import (
    ProofReport,
    validate_proof_report,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import Z3Runner


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pytest.ini").exists():
            return candidate
    raise RuntimeError("repository root not found")


CORPUS_DIR = _repo_root() / "tests" / "fixtures" / "security_ir" / "v1"
MANIFEST = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))


def _load_model_payload(model_name: str) -> dict[str, Any]:
    fixture = MANIFEST["models"][model_name]
    return json.loads((CORPUS_DIR / fixture["path"]).read_text(encoding="utf-8"))


def _sha256_label(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _cid_v1_raw_sha2_256(payload: bytes) -> str:
    """Encode the optional utility's fixed CIDv1/raw/SHA-256 profile."""

    cid_bytes = b"\x01\x55\x12\x20" + hashlib.sha256(payload).digest()
    return "b" + base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")


def _read_path(root: Any, path: list[str | int]) -> Any:
    current = root
    for component in path:
        if isinstance(component, int):
            current = current[component]
        elif isinstance(current, SecurityModelIR):
            current = getattr(current, component)
        else:
            current = current[component]
    return current


def _resolve_parent(root: Any, path: list[str | int]) -> tuple[Any, str | int]:
    if not path:
        raise AssertionError("a mutation path must not be empty")
    return _read_path(root, path[:-1]), path[-1]


def _apply_mutation(payload: Any, mutation: Mapping[str, Any]) -> None:
    parent, leaf = _resolve_parent(payload, list(mutation["path"]))
    operation = mutation["operation"]
    if operation == "set":
        parent[leaf] = copy.deepcopy(mutation["value"])
    elif operation == "delete":
        del parent[leaf]
    else:
        raise AssertionError(f"unsupported manifest mutation operation: {operation}")


def _reverse_mapping_items(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _reverse_mapping_items(item)
            for key, item in reversed(list(value.items()))
        }
    if isinstance(value, list):
        return [_reverse_mapping_items(item) for item in value]
    return value


def test_manifest_indexes_the_complete_v1_corpus() -> None:
    assert MANIFEST["schema_version"] == "security-ir-legacy-golden-corpus/v1"
    assert MANIFEST["interface"] == "SecurityIRLegacyGoldenCorpus@1"
    assert list(MANIFEST) == [
        "schema_version",
        "interface",
        "description",
        "models",
        "invalid_payloads",
        "mutable_input_regressions",
        "collection_order_cases",
        "legacy_proof_artifacts",
        "solver_availability",
    ]
    assert list(MANIFEST["models"]) == ["exchange", "xaman"]
    assert [case["id"] for case in MANIFEST["invalid_payloads"]] == [
        "unknown-top-level-field",
        "missing-required-model-id",
        "unsupported-prover-target",
        "dangling-wallet-owner",
        "unknown-claim-domain",
    ]
    assert [case["id"] for case in MANIFEST["mutable_input_regressions"]] == [
        "caller-owned-nested-list-is-retained",
        "caller-owned-nested-record-is-retained",
        "default-assumption-records-are-shared",
    ]
    assert [case["id"] for case in MANIFEST["collection_order_cases"]] == [
        "mapping-insertion-order-is-ignored",
        "entity-list-order-is-preserved",
        "set-like-action-order-is-still-preserved-by-legacy-code",
        "derived-solver-result-changes-model-identity",
    ]
    assert {path.name for path in CORPUS_DIR.iterdir() if path.is_file()} == {
        "manifest.json",
        "exchange_model.json",
        "xaman_model.json",
    }


@pytest.mark.parametrize("model_name", ["exchange", "xaman"])
def test_valid_model_canonical_bytes_and_both_legacy_identifiers(
    model_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = MANIFEST["models"][model_name]
    fixture_path = CORPUS_DIR / fixture["path"]
    raw_bytes = fixture_path.read_bytes()
    payload = json.loads(raw_bytes)

    assert hashlib.sha256(raw_bytes).hexdigest() == fixture["file_sha256"]
    model = SecurityModelIR.from_untrusted_dict(payload, strict=True)
    assert validate_ir(model) is model
    assert model.to_dict() == payload
    assert model.model_id == fixture["model_id"]

    canonical = canonicalize_ir(model)
    expected = fixture["canonical_utf8"]
    assert len(canonical) == expected["byte_length"]
    assert _sha256_label(canonical) == expected["sha256_fallback"]

    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: None)
    assert cid_module.calculate_model_cid(model) == expected["sha256_fallback"]

    observed: list[bytes] = []

    def frozen_cid_implementation(data: bytes) -> str:
        observed.append(data)
        return _cid_v1_raw_sha2_256(data)

    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: frozen_cid_implementation)
    assert _cid_v1_raw_sha2_256(canonical) == expected["cid_v1_raw_sha2_256"]
    assert cid_module.calculate_model_cid(model) == expected["cid_v1_raw_sha2_256"]
    assert observed == [canonical]

    assert {
        field_name: len(getattr(model, field_name))
        for field_name in fixture["expected_counts"]
    } == fixture["expected_counts"]
    domains = sorted(set(claim_domains(model).values()))
    assert domains == fixture["expected_claim_domains"]
    assert validate_domain_coverage(model, required_domains=domains) is model


@pytest.mark.parametrize(
    "case",
    MANIFEST["invalid_payloads"],
    ids=lambda case: case["id"],
)
def test_invalid_payloads_fail_with_exact_diagnostics(case: Mapping[str, Any]) -> None:
    payload = _load_model_payload(case["base_model"])
    _apply_mutation(payload, case["mutation"])

    with pytest.raises(ValueError) as exc_info:
        validate_ir(SecurityModelIR.from_untrusted_dict(payload, strict=True))

    assert type(exc_info.value).__name__ == case["expected_exception"]
    assert str(exc_info.value) == case["expected_message"]


@pytest.mark.parametrize(
    "case",
    MANIFEST["mutable_input_regressions"][:2],
    ids=lambda case: case["id"],
)
def test_caller_owned_nested_values_remain_aliased_by_legacy_decoder(
    case: Mapping[str, Any],
) -> None:
    payload = _load_model_payload(case["base_model"])
    model = SecurityModelIR.from_untrusted_dict(payload, strict=True)
    validate_ir(model)
    canonical_before = canonicalize_ir(model)

    _apply_mutation(payload, case["mutation"])
    path = list(case["mutation"]["path"])
    assert _read_path(model, path) == case["mutation"]["value"]
    assert case["expected_legacy_alias"] is True
    assert canonicalize_ir(model) != canonical_before
    if "expected_canonical_sha256" in case:
        assert _sha256_label(canonicalize_ir(model)) == case["expected_canonical_sha256"]


def test_nested_default_assumption_records_are_shared_between_legacy_models() -> None:
    case = MANIFEST["mutable_input_regressions"][2]
    first = SecurityModelIR(schema_version="security-model-ir/v1", model_id="first")
    second = SecurityModelIR(schema_version="security-model-ir/v1", model_id="second")
    first_assumption = first.assumptions[0]
    second_assumption = second.assumptions[0]

    assert isinstance(first_assumption, MutableMapping)
    assert first_assumption is second_assumption is DEFAULT_THREAT_MODEL_ASSUMPTIONS[0]
    original = first_assumption["description"]
    try:
        _apply_mutation(first, case["mutation"])
        assert second_assumption["description"] == case["mutation"]["value"]
        assert case["expected_second_model_observes_mutation"] is True
    finally:
        first_assumption["description"] = original


@pytest.mark.parametrize(
    "case",
    MANIFEST["collection_order_cases"],
    ids=lambda case: case["id"],
)
def test_legacy_collection_order_semantics(case: Mapping[str, Any]) -> None:
    payload = _load_model_payload(case["base_model"])
    canonical_before = canonicalize_ir(SecurityModelIR.from_untrusted_dict(payload, strict=True))

    if case["operation"] == "reverse_mapping_items_recursively":
        mutated = _reverse_mapping_items(payload)
    else:
        mutated = copy.deepcopy(payload)
        target = _read_path(mutated, list(case["path"]))
        if case["operation"] == "reverse":
            assert isinstance(target, MutableSequence)
            target.reverse()
        elif case["operation"] == "append":
            assert isinstance(target, MutableSequence)
            target.append(copy.deepcopy(case["value"]))
        else:
            raise AssertionError(f"unsupported collection operation: {case['operation']}")

    canonical_after = canonicalize_ir(
        SecurityModelIR.from_untrusted_dict(mutated, strict=True)
    )
    assert (canonical_after == canonical_before) is case["expected_canonical_equal"]
    assert _sha256_label(canonical_after) == case["expected_canonical_sha256"]


def test_legacy_report_and_receipt_match_exact_golden_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: None)
    artifacts = MANIFEST["legacy_proof_artifacts"]

    report = ProofReport.from_untrusted_dict(artifacts["report"])
    assert validate_proof_report(report) is report
    assert report.to_dict() == artifacts["report"]
    assert report.verify_report_cids() is True

    receipt = ProofReceipt.from_untrusted_dict(artifacts["receipt"], report=report)
    assert validate_proof_receipt(receipt) is receipt
    assert receipt.to_dict() == artifacts["receipt"]
    assert receipt.proof_report_cid == report.cid
    assert receipt.model_cid == report.model_cid
    assert receipt.claim_id == report.claim_id


def test_unavailable_required_solver_is_asserted_as_unknown_not_skipped_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = MANIFEST["solver_availability"]
    model = SecurityModelIR.from_untrusted_dict(_load_model_payload("exchange"), strict=True)
    claim = default_claims()[0]
    monkeypatch.setattr(cid_module, "_load_cid_for_bytes", lambda: None)
    monkeypatch.setattr(Z3Runner, "is_available", staticmethod(lambda: False))

    assert metadata == {
        "solver": "z3",
        "probe": "Z3Runner.is_available",
        "fixture_mode": "simulated-unavailable",
        "probe_result": False,
        "required_for_proof_success": True,
        "skipped_is_success": False,
        "accepted_success_statuses": ["PROVED"],
        "expected_report": {
            "status": "UNKNOWN",
            "prover": "z3",
            "solver_name": "z3",
            "solver_result": "unknown",
            "reason_unknown": "Z3 is not installed",
            "proof_or_trace_cid": "",
        },
    }
    assert Z3Runner.is_available() is metadata["probe_result"]

    report = Z3Runner(timeout_ms=1).run_claim(claim, model)
    assert {
        field_name: getattr(report, field_name)
        for field_name in metadata["expected_report"]
    } == metadata["expected_report"]
    assert report.status not in metadata["accepted_success_statuses"]
    assert metadata["skipped_is_success"] is False
