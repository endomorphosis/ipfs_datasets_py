"""Real pinned-parent fallback inference and existing modality registry binding."""
from copy import deepcopy
import json
from pathlib import Path
import os

import pytest
import importlib.util
_fixture_spec=importlib.util.spec_from_file_location("codebase_lifecycle_acceptance_fixture",Path(__file__).with_name("test_codebase_training_lifecycle.py"))
_fixture=importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture)
current, envelope=_fixture.current, _fixture.envelope
from ipfs_datasets_py.logic.software_contracts import codebase_runtime_384 as runtime
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as source384
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_modality_contracts as contracts
from ipfs_accelerate_py.agent_supervisor.runtime import repository_resource_bridge as bridge


def args(current):
    return dict(expected_head=current.head, registry=current.registry, version_id=current.parent,
        paths=['holdout_0.py','holdout_1.py','holdout_2.py'],
        embedding_snapshot=os.environ['CODEBASE384_EMBEDDING_SNAPSHOT'])


def infer(current, **options):
    with envelope(current) as parent:
        with parent.phase(bridge.RepositoryPhaseDemand('inference', memory_mb=4096)) as phase:
            result=runtime.infer_shared_parent(current.index,current.repo,**dict(args(current),**options),**phase.native_options())
    current.results.append(result)
    return result


def test_modality_contract_uses_existing_exact_local_registry_and_separate_objectives():
    registry=contracts.ModalityAdapterRegistry()
    adapter=runtime.register_runtime(registry)
    contract=contracts.ModalityContract.from_dict(adapter.contract.to_dict())
    assert registry.resolve(contract,required_capabilities=('train','evaluate')) is adapter
    assert contract.domain=='codebase_ir' and contract.embedding.dimension==384
    value=runtime.describe_runtime()
    assert set(value['objectives'])=={'feature','structured','property'}
    assert not value['objectives']['property']['learned_here']
    assert not value['resume_contract']['exact_optimizer_resume']
    assert not value['resume_contract']['head_weight_initialization']
    assert value['resume_contract']['optimizer_steps']==0
    assert not value['training_executed']
    changed=deepcopy(contract.to_dict());changed['domain']='security_ir'
    with pytest.raises(contracts.ModalityContractError,match='no local adapter'):
        registry.resolve(contracts.ModalityContract.from_dict(changed))


def test_actual_parent_weights_and_target_free_captured_source_produce_three_aligned_candidates(current,monkeypatch):
    calls=[]
    worker=source384._worker
    def inspect_payload(payload,**options):
        assert payload['action']=='infer' and set(payload['rows'][0])=={'id','source_text'}
        assert not {'target','corpus','teacher','selections'} & set(payload)
        calls.append(payload)
        return worker(payload,**options)
    def no_fit(*a,**k):pytest.fail('parent inference attempted training')
    with monkeypatch.context() as patch:
        patch.setattr(source384,'train_current_source384',no_fit)
        patch.setattr(source384,'_worker',inspect_payload)
        report=infer(current)
    assert len(calls)==1 and report['provenance_kind']=='pinned_shared_parent_inference'
    assert report['version_id']==current.parent and len(report['source_inventory'])==3
    assert all(r['source_contract']['status']=='qualified' for r in report['inference']['rows'])
    assert not report['training_executed'] and not report['training_labels_used']
    assert report['source_input_sha256']==source384._sha(source384._raw(calls[0]['rows']))
    assert report['runtime_checkpoint_sha256']==source384._sha(source384._raw(calls[0]['checkpoint']))
    assert current.registry.resolve_head(current.variant,'main')==current.model_head


def test_actual_zero_head_parent_control_retains_rejected_predictions(current):
    report=infer(current,weight_ablation='zero_head')
    rows=report['inference']['rows']
    assert len(rows)==3 and any(r['source_contract']['status']!='qualified' for r in rows)
    assert not report['training_executed'] and report['weight_ablation']=='zero_head'


def test_actual_post_inference_source_change_cannot_return_current_inference(current,monkeypatch):
    path=current.repo/'holdout_0.py';original=path.read_bytes()
    worker=source384._worker
    def change_after_real_inference(*a,**k):
        result=worker(*a,**k)
        path.write_text(original.decode().replace(' >= ',' <= '))
        return result
    try:
        with monkeypatch.context() as patch:
            patch.setattr(source384,'_worker',change_after_real_inference)
            with pytest.raises(StaleCodebaseError):infer(current)
    finally:path.write_bytes(original)


@pytest.mark.parametrize('paths',[[],['../holdout_0.py'],['holdout_0.py','holdout_0.py'],['missing.py']])
def test_parent_inference_requires_exact_selected_capture_paths(current,paths):
    with pytest.raises(ValueError):
        runtime._source_inputs(current.index,current.head,paths)


def test_parent_inference_rejects_caller_training_labels(current):
    with pytest.raises(TypeError,match='target'):
        runtime.infer_shared_parent(current.index,current.repo,**args(current),target={'operator':'multiply'})


def test_literal_and_guard_collision_candidates_remain_unsupported_in_actual_model_output(current):
    new={'literal.py':'def calculate(capacity: int, threshold: int) -> int:\n    return capacity + 1\n',
         'guard.py':'def calculate(capacity: int, threshold: int) -> int:\n    if threshold > 0:\n        return capacity + threshold\n    return capacity - threshold\n'}
    for path,text in new.items():(current.repo/path).write_text(text)
    with envelope(current) as parent:
        with parent.phase(bridge.RepositoryPhaseDemand('scan',memory_mb=4096)) as phase:
            current.head=current.index.prepare_current(current.repo,repository_id=current.head.repository_id,
                operation_id='literal-guard-collision-source',expected_head=current.head,**phase.native_options()).head
    report=infer(current,paths=list(new))
    assert len(report['inference']['rows'])==2
    for row in report['inference']['rows']:
        assert row['source_contract']['status']=='unsupported'
        assert row['candidate_ir'] is not None
        assert not row['source_contract']['proof_authority']
