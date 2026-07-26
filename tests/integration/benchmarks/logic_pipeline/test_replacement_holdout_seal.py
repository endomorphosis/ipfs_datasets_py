"""Synthetic, data-free tests for the HSSL-G220 trust boundary.

These tests use an arbitrary opaque byte string in a temporary directory.
They do not load the benchmark corpus, either holdout, case labels, expected
IR, proof obligations, or outcomes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.logic_pipeline.cases import (
    CorpusContractError,
    ReplacementHoldoutSeal,
    validate_replacement_holdout_external_path,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.logic_pipeline.holdout_execution import (
    G232_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA,
    G232ReplacementHoldoutAuthorization,
    HoldoutExecutionError,
    ReplacementHoldoutAccessReceipt,
    load_authorized_replacement_holdout,
    load_replacement_holdout_access_receipts,
)
from tests.integration.benchmarks.logic_pipeline._synthetic_seal_support import (
    OPAQUE_SYNTHETIC_BLOCK,
    _protocol_cids,
    _seal,
)


def _authorization(
    seal: ReplacementHoldoutSeal,
) -> G232ReplacementHoldoutAuthorization:
    payload = {
        "schema": G232_REPLACEMENT_HOLDOUT_AUTHORIZATION_SCHEMA,
        "goal_id": "HSSL-G232",
        "pilot_artifact_cid": cid_for_dag_json(
            {"synthetic_complete_pilot": True}
        ),
        "seal_contract_cid": seal.seal_contract_cid,
        "sealed_manifest_cid": seal.sealed_manifest_cid,
        "protocol_cids": {
            key: seal.protocol_cids[key]
            for key in ("causal_proof", "holdout_execution", "semantic")
        },
        "source_commit": "a" * 40,
        "authorized_variant_ids": ("A0", "A1"),
        "cache_modes": ("cold", "warm"),
        "passed": True,
        "complete": True,
        "shortlist_frozen": True,
        "holdout_authorized": True,
        "outcomes_inspected": False,
        "tuning_permitted": False,
    }
    cid_payload = {
        **payload,
        "authorized_variant_ids": list(payload["authorized_variant_ids"]),
        "cache_modes": list(payload["cache_modes"]),
    }
    return G232ReplacementHoldoutAuthorization(
        **payload,
        authorization_cid=cid_for_dag_json(cid_payload),
    )


def _private_external_file(
    tmp_path: Path,
    opaque_block: bytes = OPAQUE_SYNTHETIC_BLOCK,
) -> tuple[Path, Path]:
    tuning_worktree = tmp_path / "tuning-worktree"
    custody_root = tmp_path / "independent-custody"
    tuning_worktree.mkdir(mode=0o700)
    custody_root.mkdir(mode=0o700)
    sealed_path = custody_root / "opaque.seal"
    sealed_path.write_bytes(opaque_block)
    sealed_path.chmod(0o600)
    return tuning_worktree, sealed_path


class _SyntheticCustodian:
    def __init__(
        self,
        opaque_block: bytes,
        ledger_path: Path,
    ) -> None:
        self.opaque_block = opaque_block
        self.ledger_path = ledger_path
        self.calls = 0
        self.grant_was_durable_before_release = False

    @property
    def custodian_id(self) -> str:
        return cid_for_dag_json({"synthetic_actor": "custodian"})

    def release_sealed_manifest(
        self,
        sealed_manifest_path: Path,
        *,
        seal_contract_cid: str,
        authorization_cid: str,
        g241_release_receipt_cid: str,
        access_grant_receipt_cid: str,
    ) -> bytes:
        self.calls += 1
        receipts = load_replacement_holdout_access_receipts(
            self.ledger_path,
            allow_pending_grant=True,
        )
        grant = receipts[-1]
        self.grant_was_durable_before_release = (
            grant.event == "access_granted"
            and grant.receipt_cid == access_grant_receipt_cid
            and grant.seal_contract_cid == seal_contract_cid
            and grant.authorization_cid == authorization_cid
            and grant.g241_release_receipt_cid
            == g241_release_receipt_cid
            and sealed_manifest_path.is_absolute()
        )
        return self.opaque_block


class _InterruptingCustodian:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def custodian_id(self) -> str:
        return cid_for_dag_json({"synthetic_actor": "interrupting-custodian"})

    def release_sealed_manifest(
        self,
        sealed_manifest_path: Path,
        *,
        seal_contract_cid: str,
        authorization_cid: str,
        g241_release_receipt_cid: str,
        access_grant_receipt_cid: str,
    ) -> bytes:
        self.calls += 1
        raise KeyboardInterrupt("synthetic process interruption after grant")


def test_public_seal_exposes_only_opaque_metadata_and_cids() -> None:
    seal = _seal()
    record = seal.to_dict()

    assert set(record) == {
        "schema",
        "sealed_manifest_cid",
        "case_count",
        "strata_counts",
        "protocol_cids",
        "access_ledger_authority_cid",
        "seal_contract_cid",
    }
    assert not {
        "case_ids",
        "source_text",
        "labels",
        "expected_ir",
        "proof_obligations",
        "outcomes",
        "path",
    } & set(record)
    assert validate_cid(
        seal.sealed_manifest_cid, codecs=("raw",)
    ) == seal.sealed_manifest_cid
    assert validate_cid(
        seal.seal_contract_cid, codecs=("dag-json",)
    ) == seal.seal_contract_cid
    assert validate_cid(
        seal.access_ledger_authority_cid,
        codecs=("dag-json",),
    ) == seal.access_ledger_authority_cid
    assert ReplacementHoldoutSeal.from_dict(record) == seal

    invalid = dict(record)
    invalid["strata_counts"] = {"alpha": 1}
    invalid["seal_contract_cid"] = cid_for_dag_json(
        {key: invalid[key] for key in record if key != "seal_contract_cid"}
    )
    with pytest.raises(CorpusContractError, match="sum to case_count"):
        ReplacementHoldoutSeal.from_dict(invalid)


def test_external_path_boundary_rejects_tuning_files_and_symlinks(
    tmp_path: Path,
) -> None:
    tuning_worktree, sealed_path = _private_external_file(tmp_path)
    assert validate_replacement_holdout_external_path(
        sealed_path,
        tuning_worktree=tuning_worktree,
    ) == sealed_path

    in_tree = tuning_worktree / "forbidden.seal"
    in_tree.write_bytes(OPAQUE_SYNTHETIC_BLOCK)
    in_tree.chmod(0o600)
    with pytest.raises(CorpusContractError, match="tuning worktree"):
        validate_replacement_holdout_external_path(
            in_tree,
            tuning_worktree=tuning_worktree,
        )

    link = sealed_path.parent / "alias.seal"
    link.symlink_to(sealed_path)
    with pytest.raises(CorpusContractError, match="symbolic link"):
        validate_replacement_holdout_external_path(
            link,
            tuning_worktree=tuning_worktree,
        )


def test_premature_request_appends_invalidation_and_never_calls_custodian(
    tmp_path: Path,
) -> None:
    tuning_worktree, sealed_path = _private_external_file(tmp_path)
    ledger = tmp_path / "receipts" / "replacement-access.jsonl"
    seal = _seal(ledger_path=ledger)
    authorization = _authorization(seal)
    custodian = _SyntheticCustodian(OPAQUE_SYNTHETIC_BLOCK, ledger)

    with pytest.raises(HoldoutExecutionError, match="premature"):
        load_authorized_replacement_holdout(
            seal,
            None,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=ledger,
            executor_id="synthetic-executor",
            custodian=custodian,
        )

    receipts = load_replacement_holdout_access_receipts(ledger)
    assert len(receipts) == 1
    assert receipts[0].event == "premature_access"
    assert receipts[0].invalidates_seal is True
    assert receipts[0].access_authorized is False
    assert validate_cid(
        receipts[0].receipt_cid, codecs=("dag-json",)
    ) == receipts[0].receipt_cid
    assert custodian.calls == 0

    integer_flag = receipts[0].to_dict()
    integer_flag["access_authorized"] = 0
    integer_flag["receipt_cid"] = cid_for_dag_json(
        {
            key: value
            for key, value in integer_flag.items()
            if key != "receipt_cid"
        }
    )
    with pytest.raises(HoldoutExecutionError, match="event flags"):
        ReplacementHoldoutAccessReceipt.from_dict(integer_flag)

    with pytest.raises(HoldoutExecutionError, match="permanently invalidated"):
        load_authorized_replacement_holdout(
            seal,
            authorization,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=ledger,
            executor_id="synthetic-executor",
            custodian=custodian,
        )
    assert custodian.calls == 0


def test_exact_g232_proposal_alone_is_non_authorizing(
    tmp_path: Path,
) -> None:
    tuning_worktree, sealed_path = _private_external_file(tmp_path)
    ledger = tmp_path / "receipts" / "replacement-access.jsonl"
    seal = _seal(ledger_path=ledger)
    authorization = _authorization(seal)
    custodian = _SyntheticCustodian(OPAQUE_SYNTHETIC_BLOCK, ledger)

    with pytest.raises(
        HoldoutExecutionError,
        match="G241|premature",
    ):
        load_authorized_replacement_holdout(
            seal,
            authorization,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=ledger,
            executor_id="detached-executor",
            custodian=custodian,
        )

    assert custodian.calls == 0
    assert custodian.grant_was_durable_before_release is False
    receipts = load_replacement_holdout_access_receipts(ledger)
    assert [item.event for item in receipts] == ["premature_access"]
    assert receipts[0].authorization_cid == authorization.authorization_cid
    assert receipts[0].pilot_artifact_cid == authorization.pilot_artifact_cid
    assert receipts[0].g241_release_receipt_cid is None

    forged_grant = receipts[0].to_dict()
    forged_grant.update(
        {
            "event": "access_granted",
            "access_authorized": True,
            "invalidates_seal": False,
        }
    )
    forged_grant["receipt_cid"] = cid_for_dag_json(
        {
            key: value
            for key, value in forged_grant.items()
            if key != "receipt_cid"
        }
    )
    with pytest.raises(HoldoutExecutionError, match="event flags"):
        ReplacementHoldoutAccessReceipt.from_dict(forged_grant)


def test_g241_boundary_precedes_any_sealed_path_resolution(
    tmp_path: Path,
) -> None:
    tuning_worktree = tmp_path / "tuning-worktree"
    tuning_worktree.mkdir(mode=0o700)
    forbidden_path = tuning_worktree / "must-not-be-opened.seal"
    ledger = tmp_path / "receipts" / "replacement-access.jsonl"
    seal = _seal(ledger_path=ledger)
    authorization = _authorization(seal)
    custodian = _SyntheticCustodian(OPAQUE_SYNTHETIC_BLOCK, ledger)

    with pytest.raises(HoldoutExecutionError, match="G241"):
        load_authorized_replacement_holdout(
            seal,
            authorization,
            sealed_manifest_path=forbidden_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=ledger,
            executor_id="detached-executor",
            custodian=custodian,
        )

    assert not forbidden_path.exists()
    assert custodian.calls == 0
    receipts = load_replacement_holdout_access_receipts(ledger, seal=seal)
    assert [receipt.event for receipt in receipts] == ["premature_access"]


def test_stale_g232_seal_binding_invalidates_without_release(
    tmp_path: Path,
) -> None:
    tuning_worktree, sealed_path = _private_external_file(tmp_path)
    ledger = tmp_path / "receipts" / "replacement-access.jsonl"
    seal = _seal(ledger_path=ledger)
    other_protocols = _protocol_cids()
    other_protocols["semantic"] = cid_for_dag_json(
        {"synthetic_protocol": "semantic", "revision": 999}
    )
    stale_authorization = _authorization(
        _seal(protocol_cids=other_protocols, ledger_path=ledger)
    )
    custodian = _SyntheticCustodian(OPAQUE_SYNTHETIC_BLOCK, ledger)

    with pytest.raises(HoldoutExecutionError, match="premature"):
        load_authorized_replacement_holdout(
            seal,
            stale_authorization,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=ledger,
            executor_id="synthetic-executor",
            custodian=custodian,
        )

    receipts = load_replacement_holdout_access_receipts(ledger)
    assert [item.event for item in receipts] == ["premature_access"]
    assert receipts[0].authorization_cid == (
        stale_authorization.authorization_cid
    )
    assert custodian.calls == 0


def test_custody_bytes_are_not_inspected_without_g241_release(
    tmp_path: Path,
) -> None:
    tuning_worktree, sealed_path = _private_external_file(tmp_path)
    ledger = tmp_path / "receipts" / "replacement-access.jsonl"
    seal = _seal(ledger_path=ledger)
    authorization = _authorization(seal)
    custodian = _SyntheticCustodian(b"wrong synthetic block", ledger)

    with pytest.raises(HoldoutExecutionError, match="G241"):
        load_authorized_replacement_holdout(
            seal,
            authorization,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=ledger,
            executor_id="synthetic-executor",
            custodian=custodian,
        )

    receipts = load_replacement_holdout_access_receipts(ledger)
    assert [item.event for item in receipts] == ["premature_access"]
    assert receipts[-1].invalidates_seal is True
    assert receipts[-1].g241_release_receipt_cid is None
    assert custodian.calls == 0


def test_seal_invalidation_cannot_be_bypassed_with_a_fresh_ledger(
    tmp_path: Path,
) -> None:
    tuning_worktree, sealed_path = _private_external_file(tmp_path)
    canonical_ledger = (
        tmp_path / "receipts" / "canonical-replacement-access.jsonl"
    )
    fresh_ledger = tmp_path / "receipts" / "fresh-bypass.jsonl"
    seal = _seal(ledger_path=canonical_ledger)
    authorization = _authorization(seal)
    canonical_custodian = _SyntheticCustodian(
        OPAQUE_SYNTHETIC_BLOCK,
        canonical_ledger,
    )

    with pytest.raises(HoldoutExecutionError, match="premature"):
        load_authorized_replacement_holdout(
            seal,
            None,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=canonical_ledger,
            executor_id="synthetic-executor",
            custodian=canonical_custodian,
        )

    bypass_custodian = _SyntheticCustodian(
        OPAQUE_SYNTHETIC_BLOCK,
        fresh_ledger,
    )
    with pytest.raises(HoldoutExecutionError, match="seal-bound ledger"):
        load_authorized_replacement_holdout(
            seal,
            authorization,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=fresh_ledger,
            executor_id="synthetic-executor",
            custodian=bypass_custodian,
        )

    assert bypass_custodian.calls == 0
    assert not fresh_ledger.exists()
    receipts = load_replacement_holdout_access_receipts(
        canonical_ledger,
        seal=seal,
    )
    assert [item.event for item in receipts] == ["premature_access"]


def test_custodian_is_not_called_before_g241_release_validation(
    tmp_path: Path,
) -> None:
    tuning_worktree, sealed_path = _private_external_file(tmp_path)
    ledger = tmp_path / "receipts" / "replacement-access.jsonl"
    seal = _seal(ledger_path=ledger)
    authorization = _authorization(seal)
    interrupting_custodian = _InterruptingCustodian()

    with pytest.raises(HoldoutExecutionError, match="G241"):
        load_authorized_replacement_holdout(
            seal,
            authorization,
            sealed_manifest_path=sealed_path,
            tuning_worktree=tuning_worktree,
            access_ledger_path=ledger,
            executor_id="synthetic-executor",
            custodian=interrupting_custodian,
        )

    assert interrupting_custodian.calls == 0
    receipts = load_replacement_holdout_access_receipts(ledger, seal=seal)
    assert [item.event for item in receipts] == ["premature_access"]
    assert receipts[0].g241_release_receipt_cid is None
