from pathlib import Path
import json
import pytest
from ipfs_datasets_py.logic.intent_ir.formalize import alignment_training as training,rich_grammar as grammar


def corpus():
    rows=[]
    for split,left,right in [('train','copper memo','emerald packet'),('validation','bronze folio','amber ledger'),('test','violet receipt','cobalt card')]:
        for i,text in enumerate((f'Save {left}.',f'View {right}.',f'Save {left} and view {right}.')):
            rows.append({'id':split+str(i),'split':split,'instruction':text,'ast':grammar.parse_instruction(text),'provenance':{}})
    return {'samples':rows}


def parent():
    root=Path(__file__).resolve().parents[7]
    path=root/'artifacts/ir-training-coverage-20261002/intent-01/source-run-receipt-02.json'
    if not path.exists():pytest.skip('local legal-initialized development parent absent')
    return json.loads(path.read_bytes())['backend']


def invoke(tmp_path,**kw):
    import torch
    torch.set_num_threads(1)
    return training.train_aligned_intent(corpus(),parent_backend_descriptor=parent(),
        expected_legal_initializer_sha256='9c14e44359da4e2259476acbb239595f0c3c625be6c2f0dc777485f3c05110e0',
        output=tmp_path/'child',source_training_options={'epochs':1,'max_seconds':15},
        family_target_limits={'train':3,'validation':3},**kw)


def test_actual_joint_default_fits_source_and_native_family(tmp_path):
    result=invoke(tmp_path,family_training_options={'epochs':1,'max_seconds':15,'latent_width':2,'patience':1})
    assert result['status']=='complete' and result['family_stage']=='complete'
    assert result['source_descriptor']['schema']=='shared-paired-copy-aligned-continuation/v2'
    assert result['family_descriptor']is not None
    assert result['family_report']['training_executed']
    assert result['test_used_for_fit_or_selection']is False
    assert result['default_supervisor_dispatch_changed']is False


def test_family_failure_preserves_actual_source_child(tmp_path,monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_v2 as numerical
    def fail(*a,**kw):raise ValueError('controlled family failure')
    monkeypatch.setattr(numerical,'train_family_projection_autoencoder_v2',fail)
    result=invoke(tmp_path)
    assert result['status']=='partial' and result['family_stage']=='failed'
    assert Path(result['source_descriptor']['path']).exists()
    assert result['family_error']['message']=='controlled family failure'
    assert json.loads((tmp_path/'child'/'receipt.json').read_bytes())==result


def test_false_mode_rejects_silent_family_settings_before_output(tmp_path):
    with pytest.raises(ValueError,match='family settings'):
        invoke(tmp_path,train_family_projection=False,family_training_options={'epochs':1})
    assert not(tmp_path/'child').exists()


def test_all_training_aliases_heldout_fail_before_optimizer_or_output(tmp_path):
    data=corpus()
    train=[r for r in data['samples']if r['split']=='train']
    data['samples']=[*train,*[{**r,'id':'heldout:'+r['id'],'split':'validation'}for r in train]]
    with pytest.raises(ValueError):
        training.train_aligned_intent(data,parent_backend_descriptor=parent(),
            expected_legal_initializer_sha256='9c14e44359da4e2259476acbb239595f0c3c625be6c2f0dc777485f3c05110e0',
            output=tmp_path/'child',source_training_options={'epochs':1},train_family_projection=False)
    assert not(tmp_path/'child').exists()
