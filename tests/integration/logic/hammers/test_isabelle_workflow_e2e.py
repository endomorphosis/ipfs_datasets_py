"""Real public hammer workflow: Isabelle -> SMT portfolio -> kernel -> receipt.

These tests never mock native execution. A solver candidate alone remains
untrusted; even a candidate for a valid formula cannot certify a false native
statement. Missing native dependencies are explicit skips.
"""
import asyncio
import json
import subprocess
import sys
import shutil

import pytest

from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest, CorpusSource
from ipfs_datasets_py.logic.hammers.frontends.isabelle import IsabelleFrontend
from ipfs_datasets_py.logic.hammers.models import (
    EnvironmentLockRecord, HammerPolicy, HammerRequest, HammerResult,
    HammerResultStatus, ITPKind, ProofCandidateRecord, ReconstructionRecord,
    TranslationRecord,
)
from ipfs_datasets_py.logic.hammers.portfolio import PortfolioRunResult
from ipfs_datasets_py.logic.hammers.provenance import NormalizedEvidence
from ipfs_datasets_py.logic.hammers.receipts import HammerReceipt
from ipfs_datasets_py.logic.hammers.reconstruction import ReconstructionEvidence
from ipfs_datasets_py.mcp_server.tools import logic_hammer as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler


def call(operation, **kwargs):
    response = asyncio.run(operation(**kwargs))
    assert response['status'] == 'ok' and response['success'], response
    return response


@pytest.fixture
def live_workflow(tmp_path, monkeypatch):
    if not IsabelleFrontend().capability().available:
        pytest.skip('requires modern Isabelle runtime')
    solvers = [name for name in ('z3', 'cvc5') if shutil.which(name)]
    if not solvers:
        pytest.skip('requires real Z3 or CVC5')
    monkeypatch.delenv('IPFS_DATASETS_PROOF_RESOURCE_SAFETY', raising=False)
    monkeypatch.setenv('IPFS_DATASETS_RESOURCE_SCHEDULER_PATH', str(tmp_path / 'scheduler.json'))
    manifest = CorpusManifest(manifest_id='live-isabelle-workflow')
    manifest.register_source(CorpusSource(corpus_id='hol', name='HOL workflow',
        source_itp=ITPKind.ISABELLE, version_ref='live', license_id='BSD-3-Clause'))
    return manifest, solvers, tmp_path


def test_public_workflow_checks_and_persists_real_solver_candidate(live_workflow):
    manifest, solvers, root = live_workflow
    correlation = 'isabelle-live-workflow'
    source = 'theory IPFSWorkflow\nimports Main\nbegin\nlemma checked: "(n::nat) = n"\nsorry\nend\n'
    inspected = call(api.hammer_inspect, itp='isabelle', theorem_id='checked',
        native_source=source, timeout=60, confirm_native_execution=True, correlation_id=correlation)
    goal = inspected['data']['goal_snapshot']['goal_text']
    selected = call(api.hammer_select_premises, goal_statement=goal,
        corpus_manifest=manifest.to_dict(), theorem_id='checked', correlation_id=correlation)
    assert selected['data']['corpus_revision'] == manifest.revision
    request = HammerRequest(request_id=correlation, itp=ITPKind.ISABELLE,
        theorem_id='checked', goal_statement=goal, corpus_revision=manifest.revision,
        policy=HammerPolicy(allowed_solvers=solvers, timeout_seconds=60))
    # Refute an explicit AST for the universally quantified native goal.
    # Translation emits the supplied formula; the caller supplies its negation.
    nat = {'kind': 'sort', 'name': 'nat'}
    var = {'kind': 'var', 'name': 'n', 'type': nat}
    term = {'kind': 'forall', 'var': 'n', 'var_type': nat,
            'body': {'kind': 'eq', 'left': var, 'right': var}}
    translated = call(api.hammer_translate, request_id=request.request_id,
        source_construct='negated checked', term={'kind': 'not', 'term': term}, target='smtlib', correlation_id=correlation)
    translation = translated['data']['translation']
    ran = call(api.hammer_run_candidate, request=request.to_dict(),
        attempts=[{'translation': translation, 'solver_name': name} for name in solvers],
        portfolio_policy={'hammer_policy': request.policy.to_dict(), 'max_parallel_processes': len(solvers), 'cancel_on_first_conclusive': False},
        confirm_native_execution=True, correlation_id=correlation)
    assert ran['data']['recommended_status'] == 'candidate'
    portfolio = PortfolioRunResult.from_dict(ran['data']['run_result'])
    assert len(portfolio.attempts) == len(solvers) and not portfolio.denied
    assert all(attempt.verdict.value == 'unsat' for attempt in portfolio.attempts), portfolio.to_dict()
    candidate = ran['data']['proof_candidate']
    assert candidate and candidate['solver_attempt_id'] in portfolio.evidence
    reconstructed = call(api.hammer_reconstruct, request=request.to_dict(), candidate=candidate,
        itp='isabelle', theorem_id='checked', native_source=source, timeout=60,
        confirm_native_execution=True, correlation_id=correlation)
    data = reconstructed['data']
    assert data['status'] == 'verified' and data['reconstruction']['kernel_accepted']
    result = HammerResult(result_id=correlation, request=request, status=HammerResultStatus.VERIFIED,
        corpus_revision=manifest.revision, environment_lock=EnvironmentLockRecord.from_dict(data['environment_lock']),
        translations=[TranslationRecord.from_dict(translation)], solver_attempts=portfolio.attempts,
        proof_candidate=ProofCandidateRecord.from_dict(candidate),
        reconstruction=ReconstructionRecord.from_dict(data['reconstruction']))
    receipt = HammerReceipt(result=result,
        reconstruction_evidence=ReconstructionEvidence.from_dict(data['reconstruction_evidence']),
        solver_evidence=list(portfolio.evidence.values()),
        normalized_evidence=[NormalizedEvidence.from_dict(item) for item in ran['data']['normalized_evidence'].values()])
    store = str(root / 'receipts')
    persisted = call(api.hammer_persist_receipt, receipt=receipt.to_dict(), store_root=store,
        correlation_id=correlation)
    retrieved = call(api.hammer_retrieve_receipt, receipt_id=receipt.receipt_id,
        store_root=store, correlation_id=correlation)
    assert persisted['data']['receipt_id'] == receipt.receipt_id
    assert retrieved['data']['is_verified']
    assert retrieved['data']['receipt'] == receipt.to_dict()
    for response in (inspected, selected, translated, ran, reconstructed, persisted, retrieved):
        assert response['correlation_id'] == correlation
    scheduler = get_global_resource_scheduler()
    assert scheduler.config.proof_safety_enabled
    assert scheduler.snapshot()['active_lease_count'] == 0


def test_public_workflow_refuses_false_native_theorem(live_workflow):
    manifest, _, _ = live_workflow
    request = HammerRequest(request_id='false-native', itp=ITPKind.ISABELLE,
        theorem_id='checked', goal_statement='(0::nat) = 1', corpus_revision=manifest.revision,
        policy=HammerPolicy(timeout_seconds=60))
    candidate = ProofCandidateRecord(candidate_id='untrusted', request_id=request.request_id,
        solver_attempt_id='untrusted-proposal', premise_ids=[])
    response = call(api.hammer_reconstruct, request=request.to_dict(), candidate=candidate.to_dict(),
        itp='isabelle', theorem_id='checked', timeout=60, confirm_native_execution=True,
        native_source='theory IPFSFalseWorkflow\nimports Main\nbegin\nlemma checked: "(0::nat) = 1"\nsorry\nend\n')
    assert response['data']['status'] == 'candidate'
    assert not response['data']['reconstruction']['kernel_accepted']
    assert response['data']['reconstruction']['failure_reason']


def test_setup_cli_reuses_install_and_returns_clean_json(live_workflow):
    result = subprocess.run([sys.executable, '-m',
        'ipfs_datasets_py.logic.external_provers.isabelle_setup',
        '--install', '--smoke', '--timeout', '120'],
        capture_output=True, text=True, timeout=150, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report['installation']['successful']
    # The fixed full HOL rebuild is a separately retained heavyweight
    # qualification. Ordinary CLI reuse must not trigger it or download again.
    assert not report['installation']['receipt']['build_hol_requested']
    assert not report['installation']['receipt']['hol_build']
    assert not report['installation']['receipt']['download_attempted']
    assert report['ready'] and report['readiness_level'] == 'kernel_smoke'
    assert report['smoke']['accepted']
