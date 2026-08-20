"""Regression tests for closed ProofUnit@1 (IPS-006)."""

from __future__ import annotations

import json
import math

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.evidence import (
    EvidenceClass,
    EvidenceClassError,
    ProofMode,
    ProofTerminalStatus,
    SealStatus,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.proof_unit import (
    ABSENCE_TOKEN,
    REQUIRED_FIELDS,
    SECRET_FIELD_NAMES,
    ProofUnit,
    ProofUnitError,
    assert_unit_production_policy,
    sample_production_unit,
)


def test_all_required_fields_exist_and_round_trip() -> None:
    unit = sample_production_unit()
    payload = json.loads(unit.to_canonical_json())
    for field in REQUIRED_FIELDS:
        assert field in payload
    restored = ProofUnit.from_canonical(payload)
    assert restored == unit
    assert restored.satisfies_production()


def test_missing_unknown_duplicate_and_nonfinite_fail() -> None:
    payload = sample_production_unit().to_canonical()
    missing = dict(payload)
    del missing["proof_unit_id"]
    with pytest.raises(ProofUnitError, match="missing required fields"):
        ProofUnit.from_canonical(missing)
    with pytest.raises(EvidenceClassError, match="unknown"):
        ProofUnit.from_canonical({**payload, "proof_unit_kind": "mystery"})
    with pytest.raises(ProofUnitError, match="duplicates"):
        ProofUnit.from_canonical({**payload, "test_ids": ["a", "a"]})
    with pytest.raises(ProofUnitError, match="nonfinite"):
        ProofUnit.from_canonical({**payload, "risk_class": math.inf})


def test_typed_absence_is_the_only_omission_form() -> None:
    payload = sample_production_unit().to_canonical()
    payload["test_ids"] = ABSENCE_TOKEN
    payload["proving_key_id"] = ABSENCE_TOKEN
    unit = ProofUnit.from_canonical(payload)
    assert unit.test_ids == ()
    assert unit.proving_key_id == ABSENCE_TOKEN
    encoded = unit.to_canonical()
    assert encoded["test_ids"] == ABSENCE_TOKEN
    assert "created_at" not in encoded
    assert not (set(encoded) & SECRET_FIELD_NAMES)


def test_secret_and_timestamp_fields_are_rejected() -> None:
    payload = sample_production_unit().to_canonical()
    with pytest.raises(ProofUnitError, match="secret"):
        ProofUnit.from_canonical({**payload, "witness": "leak"})
    with pytest.raises(ProofUnitError, match="secret"):
        ProofUnit.from_canonical({**payload, "created_at": "now"})


def test_source_root_is_not_repository_state() -> None:
    payload = sample_production_unit().to_canonical()
    payload["source_root_cid"] = payload["repository_state_cid"]
    with pytest.raises(ProofUnitError, match="source-closure"):
        ProofUnit.from_canonical(payload)


def test_required_simulated_or_failed_units_cannot_satisfy_production() -> None:
    payload = sample_production_unit().to_canonical()
    payload["proof_mode"] = ProofMode.SIMULATED.value
    payload["terminal_status"] = ProofTerminalStatus.PROVED.value
    with pytest.raises(ProofUnitError, match="cannot satisfy production"):
        ProofUnit.from_canonical(payload)
    payload["terminal_status"] = ProofTerminalStatus.SIMULATED.value
    simulated = ProofUnit.from_canonical(payload)
    assert not simulated.satisfies_production()
    with pytest.raises(EvidenceClassError, match="simulated_only|cannot satisfy production"):
        assert_unit_production_policy(simulated, SealStatus.SEALED_FULL)
    failed = sample_production_unit().to_canonical()
    failed["terminal_status"] = ProofTerminalStatus.FAILED.value
    with pytest.raises(ProofUnitError, match="non-pass"):
        ProofUnit.from_canonical(failed)


def test_integrity_status_does_not_upgrade_to_proved() -> None:
    payload = sample_production_unit().to_canonical()
    payload["evidence_class"] = EvidenceClass.INTEGRITY_COMMITMENT.value
    payload["proof_mode"] = ProofMode.INTEGRITY_ONLY.value
    payload["terminal_status"] = ProofTerminalStatus.INTEGRITY_VERIFIED.value
    unit = ProofUnit.from_canonical(payload)
    assert unit.satisfies_production()
    payload["terminal_status"] = ProofTerminalStatus.PROVED.value
    upgraded = ProofUnit.from_canonical(payload)
    assert not upgraded.satisfies_production()
