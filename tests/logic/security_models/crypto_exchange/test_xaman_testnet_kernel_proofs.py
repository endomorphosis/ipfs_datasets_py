"""Tests for PORTAL-CXTP-136 Xaman Testnet Lean kernel and Coq decision."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_kernel_proofs import (
    ASSUMPTIONS_PATH,
    COQ_DECISION_PATH,
    COQ_KERNEL_PATH,
    FORMALIZED_INVARIANTS,
    LEAN_COVERED_CLAIM_IDS,
    LEAN_KERNEL_PATH,
    LEAN_REJECTED_SCOPE_CLAIM_IDS,
    LEAN_REPORT_PATH,
    LEAN_REPORT_SCHEMA_VERSION,
    LEAN_THEOREMS,
    MODEL_CID_PATH,
    MODEL_PATH,
    TASK_ID,
    TRACE_MAP_PATH,
    build_xaman_testnet_coq_coverage_decision,
    build_xaman_testnet_lean_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'
LEAN_PATH = REPO_ROOT / LEAN_KERNEL_PATH
LEAN_REPORT = REPO_ROOT / LEAN_REPORT_PATH
COQ_DECISION = REPO_ROOT / COQ_DECISION_PATH
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_kernel_proofs.md'


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid({item_key: item for item_key, item in payload.items() if item_key != key})


def _inputs() -> tuple[dict, str, dict, dict, str]:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    assumptions = _load_json(REPO_ROOT / ASSUMPTIONS_PATH)
    lean_source = LEAN_PATH.read_text(encoding='utf-8')
    return model, model_cid, trace_map, assumptions, lean_source


def test_lean_kernel_contains_expected_invariants_without_placeholders() -> None:
    body = LEAN_PATH.read_text(encoding='utf-8')

    assert 'namespace XamanTestnet' in body
    assert 'def canUseLeanEvidenceForClaim' in body
    assert 'def canCloseTestnetAssurance' in body
    assert 'ClaimStatus.modeledWithTestnetScope' in body
    assert 'ClaimStatus.modeledWithBlockingNotModeledBoundary' in body
    assert 'ClaimStatus.notModeled' in body
    assert 'KernelResult.proved' in body
    assert 'KernelResult.counterexample' in body
    assert 'KernelResult.incomplete' in body
    assert 'sorry' not in body
    assert 'admit' not in body
    for invariant in FORMALIZED_INVARIANTS:
        assert f'def {invariant}' in body
    for theorem in LEAN_THEOREMS:
        assert f'theorem {theorem}' in body


def test_lean_kernel_compiles_with_lean() -> None:
    lean = shutil.which('lean')
    assert lean is not None, 'Lean is required for PORTAL-CXTP-136 validation'

    completed = subprocess.run(
        [lean, str(LEAN_PATH)],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stderr


def test_lean_report_is_regenerable_and_bound_to_frozen_model() -> None:
    model, model_cid, trace_map, assumptions, lean_source = _inputs()
    report = _load_json(LEAN_REPORT)
    generated = build_xaman_testnet_lean_report(
        model_payload=model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        assumptions_payload=assumptions,
        lean_source=lean_source,
        lean_executable=report['lean']['executable'],
        lean_version=report['lean']['version'],
        lean_compile=report['lean']['compile'],
    )
    kernel_cid = 'sha256:' + hashlib.sha256(lean_source.encode('utf-8')).hexdigest()

    assert generated == report
    assert report['schema_version'] == LEAN_REPORT_SCHEMA_VERSION
    assert report['task_id'] == TASK_ID
    assert report['model']['cid'] == PINNED_MODEL_CID == model_cid
    assert report['kernel']['path'] == LEAN_KERNEL_PATH
    assert report['kernel']['artifact_cid'] == kernel_cid
    assert report['kernel']['contains_sorry'] is False
    assert report['kernel']['contains_admit'] is False
    assert tuple(report['kernel']['formalized_invariants']) == FORMALIZED_INVARIANTS
    assert tuple(report['kernel']['theorems']) == LEAN_THEOREMS
    assert report['report_cid'] == _cid_without(report, 'report_cid')


def test_lean_report_scope_is_checked_but_not_assurance_closing() -> None:
    report = _load_json(LEAN_REPORT)

    assert report['lean']['status'] == 'compiled'
    assert report['lean']['compile']['returncode'] == 0
    assert report['overall_status'] == 'checked_with_scope_limits'
    assert report['security_decision'] == 'LEAN_TESTNET_KERNEL_CHECKED_FORMALIZED_INVARIANTS_ONLY'
    assert report['testnet_assurance_blocked'] is True
    assert report['production_release_blocked'] is True
    assert tuple(report['coverage']['covered_claim_ids']) == LEAN_COVERED_CLAIM_IDS
    assert tuple(report['coverage']['rejected_scope_claim_ids']) == LEAN_REJECTED_SCOPE_CLAIM_IDS
    assert report['coverage']['missing_claim_ids'] == []

    policy = report['coverage']['result_policy']
    assert policy['accepted_kernel_results'] == ['proved']
    assert set(policy['rejected_kernel_results']) == {'counterexample', 'incomplete'}
    assert policy['claim_status_required'] == 'MODELED_WITH_TESTNET_SCOPE'
    assert policy['blocking_assumptions_clearance_required_for_assurance'] is True
    assert policy['runtime_equivalence_required_for_assurance'] is True
    assert policy['independent_kernel_required_for_assurance'] is True


def test_coq_coverage_decision_is_regenerable_and_declares_required_gap() -> None:
    model, model_cid, _trace_map, _assumptions, _lean_source = _inputs()
    lean_report = _load_json(LEAN_REPORT)
    decision = _load_json(COQ_DECISION)
    coq_source = None
    generated = build_xaman_testnet_coq_coverage_decision(
        model_payload=model,
        model_cid=model_cid,
        lean_report=lean_report,
        coq_kernel_source=coq_source,
        coqc_executable=decision['coq']['coqc_executable'],
        coqc_version=decision['coq']['coqc_version'],
        coq_check=decision['coq']['check'],
    )

    assert generated == decision
    assert decision['schema_version'] == 'xaman-testnet-coq-coverage-decision/v1'
    assert decision['task_id'] == TASK_ID
    assert decision['model']['cid'] == PINNED_MODEL_CID
    assert decision['lean_report']['path'] == LEAN_REPORT_PATH
    assert decision['lean_report']['formalized_invariant_only'] is True
    assert decision['coq_required_by_reviewed_threat_model'] is True
    assert decision['decision'] == 'required_missing_artifact'
    assert decision['overall_status'] == 'coverage_gap_required_independent_kernel_missing'
    assert decision['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_INDEPENDENT_COQ_KERNEL_MISSING'
    assert decision['testnet_assurance_blocked'] is True
    assert decision['coq']['kernel_path'] == COQ_KERNEL_PATH
    assert decision['coq']['kernel_present'] is False
    assert decision['coq']['check']['status'] == 'not-run'
    assert decision['coverage_gap']['missing_coq_declared_coverage_gap'] is True
    assert decision['coverage_gap']['unavailable_or_missing_coq_blocks_testnet_assurance'] is True
    assert decision['coverage_gap']['does_not_invalidate_checked_lean_formalized_invariant'] is True
    assert decision['artifact_cid'] == _cid_without(decision, 'artifact_cid')


def test_coq_decision_can_report_checked_when_artifact_and_checker_are_present(tmp_path: Path) -> None:
    model, model_cid, _trace_map, _assumptions, _lean_source = _inputs()
    lean_report = _load_json(LEAN_REPORT)
    coq_source = '(* fixture Coq translation for coverage-state test *)\n'
    checked = build_xaman_testnet_coq_coverage_decision(
        model_payload=model,
        model_cid=model_cid,
        lean_report=lean_report,
        coq_kernel_source=coq_source,
        coqc_executable=str(tmp_path / 'coqc'),
        coqc_version='The Coq Proof Assistant, version fixture',
        coq_check={
            'command': [str(tmp_path / 'coqc'), COQ_KERNEL_PATH],
            'returncode': 0,
            'status': 'passed',
            'stdout': '',
            'stderr': '',
        },
    )

    assert checked['decision'] == 'required_checked'
    assert checked['overall_status'] == 'independent_kernel_checked'
    assert checked['security_decision'] == 'COQ_INDEPENDENT_KERNEL_CHECKED'
    assert checked['coverage_gap']['missing_coq_declared_coverage_gap'] is False
    assert checked['testnet_assurance_blocked'] is False


def test_documentation_records_scope_and_coq_gap() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-136' in doc
    assert LEAN_KERNEL_PATH in doc
    assert LEAN_REPORT_PATH in doc
    assert COQ_DECISION_PATH in doc
    assert PINNED_MODEL_CID in doc
    assert 'evidence only about the predicates in `XamanTestnet.lean`' in doc
    assert 'required_missing_artifact' in doc
    assert 'Missing Coq is therefore a declared coverage gap' in doc
    assert 'does not invalidate the checked Lean formalized invariant' in doc
