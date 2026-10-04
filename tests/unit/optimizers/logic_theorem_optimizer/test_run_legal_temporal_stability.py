"""Runner selection integration, complete source-only generation and inventories."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import pytest
from scripts.ops.legal_ir import run_legal_temporal_stability as r


def source(name,index):
    text=f'{name} record{index} Registry shall file within 10 days.';a=text.index('within')
    return {'id':hashlib.sha256(text.encode()).hexdigest(),'source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span':{'char_start':a,'char_end':a+14}}


def prediction(src,target,*,wrong=False,low=False):
    index=r.runtime.CLASSES.index(target);chosen=(index+1)%4 if wrong else index
    logits=[0.]*4;logits[chosen]=1. if low else 4.
    values=[math.exp(x) for x in logits];probs=[x/sum(values) for x in values];confidence=probs[chosen]
    reason='predicted_ambiguous' if chosen==3 else 'below_fixed_confidence' if confidence<.8 else None
    return {'id':src['id'],'source_sha256':src['source_sha256'],'proposed_time_span':src['proposed_time_span'],
            'time_token_span':list(r.runtime._query(src)['time_tokens']),'logits':logits,'probabilities':probs,
            'predicted_label':r.runtime.CLASSES[chosen],'confidence':confidence,'status':'deferred' if reason else 'accepted',
            'owner_type':None if reason else r.runtime.CLASSES[chosen],'reason':reason,**r.runtime.FALSE}


def gate(name,wrong=(),low=()):
    sources=[source(name,i) for i in range(r.gates.PANEL_COUNTS[name])]
    labels={s['id']:r.runtime.CLASSES[i%4] for i,s in enumerate(sources)}
    rows=[prediction(s,labels[s['id']],wrong=i in wrong,low=i in low) for i,s in enumerate(sources)]
    return r.gates.panel_metrics(sources,rows,labels)['gate_counts']


@pytest.fixture(scope='module')
def parent():
    return {'steps':0,**{name+'_gate_counts':gate(name) for name in r.gates.PANELS}}


def stages(parent):
    return [{**deepcopy(parent),'steps':step} for step in r.STAGES]


def test_unchanged_parent_is_tie_break_fallback(parent):
    assert r.select_stage(parent,stages(parent))['steps']==0
    assert r.selection_receipt(parent,stages(parent))['eligible_steps']==[0,50,100,200]


@pytest.mark.parametrize('panel',r.gates.PANELS)
def test_each_class_correctness_floor_is_integrated(parent,panel):
    candidate=deepcopy(parent);candidate['steps']=50;candidate[panel+'_gate_counts']=gate(panel,wrong=(0,))
    assert not r.eligible(candidate,parent)


@pytest.mark.parametrize('panel',r.gates.RETENTION_PANELS)
def test_each_retention_panel_accepted_correct_coverage_is_required(parent,panel):
    candidate=deepcopy(parent);candidate['steps']=50;candidate[panel+'_gate_counts']=gate(panel,low=(0,))
    assert not r.eligible(candidate,parent)


def test_same_error_count_with_exchanged_accepted_bad_IDs_rejected(parent):
    name='old_multi_fresh';before=deepcopy(parent);before[name+'_gate_counts']=gate(name,wrong=(0,))
    candidate=deepcopy(before);candidate['steps']=50;candidate[name+'_gate_counts']=gate(name,wrong=(4,))
    assert before[name+'_gate_counts']['correct']==candidate[name+'_gate_counts']['correct']
    assert before[name+'_gate_counts']['accepted_type_errors']==candidate[name+'_gate_counts']['accepted_type_errors']
    assert not r.eligible(candidate,before)


def test_rank_uses_new_tuning_macroF1_then_NLL_then_earlier(parent):
    a,b=deepcopy(parent),deepcopy(parent);a['steps']=50;b['steps']=100
    assert r.stage_rank(a)<r.stage_rank(b)
    b['placement_tuning_gate_counts']['mean_nll']*=.5
    assert r.stage_rank(b)<r.stage_rank(a)


def test_no_current_fresh_or_missing_stage_accepted_in_selection(parent):
    with pytest.raises(ValueError):r.select_stage(parent,stages(parent)[:-1])
    candidates={s['steps']:r.stage_gates(s) for s in [parent,*stages(parent)]}
    candidates[200]['fresh_lexical']=deepcopy(candidates[200]['placement_tuning'])
    with pytest.raises(ValueError):r.gates.select_candidate(candidates)


def test_generator_passes_exact_source_only_rows_with_original48batch_policy(monkeypatch,tmp_path):
    rows=[source('generation',i) for i in range(97)];calls=[]
    class Decoder:
        encoder_batch_forwards=0;encoder_source_evaluations=0
        def predict_many(self,values):
            assert all(set(x)==r.runtime.SOURCE_KEYS for x in values)
            calls.append(deepcopy(values));self.encoder_batch_forwards+=1;self.encoder_source_evaluations+=len(values)
            return [prediction(x,'norm') for x in values]
    cp={'config':{'arm':'placement','seed':1730},'optimizer_steps':200}
    monkeypatch.setattr(r,'load_decoder',lambda pin,kind:(cp,Decoder()))
    src=r.write(tmp_path/'sources.json',rows)
    _,out=r.generate({'sha256':'1'*64},src,tmp_path/'generation.json',decoder_kind='stability_owner_type')
    assert list(map(len,calls))==[48,48,1]
    assert out['encoder_source_evaluations']==97 and out['encoder_batch_forwards']==3
    assert out['source_id_used_as_feature'] is False and out['labels_supplied'] is False
    assert out['rows'][0]['id']==rows[0]['id']
    assert out['model']['decoder_kind']=='stability_owner_type'


def test_initial_and_stage_kinds_dispatch_to_exact_frozen_or_new_loader(monkeypatch):
    calls=[]
    for module,name in ((r.runtime.previous,'paired'),(r.runtime,'placement')):
        monkeypatch.setattr(module,'load_checkpoint',lambda path,expected_sha256,n=name: calls.append((n,path,expected_sha256)) or {'model':n})
    monkeypatch.setattr(r.runtime.previous,'PairedTemporalOwnershipHead',lambda cp:cp['model'])
    monkeypatch.setattr(r.runtime,'TemporalStabilityHead',lambda cp:cp['model'])
    pin={'path':'checkpoint.json','sha256':'1'*64}
    assert r.load_decoder(pin,'paired_owner_type')[1]=='paired'
    assert r.load_decoder(pin,'stability_owner_type')[1]=='placement'
    assert [x[0] for x in calls]==['paired','placement']
    with pytest.raises(ValueError):r.load_decoder(pin,'old_owner_type')


def test_runtime_input_order_and_admitted_denominators():
    values={name:object() for name in r.runtime.INPUT_KEYS}
    assert r.training_args(values)==tuple(values[name] for name in r.runtime.INPUT_KEYS)
    counts={**dict(zip(r.TRAIN_PANELS,(768,864,864))),**r.gates.PANEL_COUNTS}
    assert sum(counts[name] for name in r.ADMITTED)==4080
    assert sum((counts[name]+47)//48 for name in r.ADMITTED)==85
    assert r.FINAL_PANELS==('fresh_lexical','fresh_structural') and len(r.runtime.ARMS)==3


def test_producer_closure_binds_frozen_runtime_runner_metric_and_new_gates():
    pins=r.producer_pins()
    for module in (r,r.runtime,r.previous_runner,r.gates,r.gates.metric,r.runtime.previous):
        path=str(Path(module.__file__).resolve())
        assert pins[path]==hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_new_guards_refuse_all_four_current_reference_paths(tmp_path):
    # The process-local hook only blocks this test's temporary reference paths.
    targets={}
    for name in r.SEALED_KEYS:
        p=tmp_path/(name+'.json');p.write_text('{}');targets[name]=r.reference(p)
    manifest=r.write(tmp_path/'manifest.json',{'artifacts':targets})
    config=r.write(tmp_path/'config.json',{'corpus_manifest':manifest})
    r.install_fresh_reference_guard(config['path'])
    for ref in targets.values():
        with pytest.raises(PermissionError):Path(ref['path']).read_bytes()


def test_reduced_admitted_inventory_keeps_every_gate_and_only_final_train_diagnostics():
    assert len(r.gates.PANELS)==9 and len(r.ADMITTED)==12
    assert r.admitted_panels(0)==r.ADMITTED and r.admitted_panels(200)==r.ADMITTED
    assert r.admitted_panels(50)==r.gates.PANELS and r.admitted_panels(100)==r.gates.PANELS
    counts={**dict(zip(r.TRAIN_PANELS,(768,864,864))),**r.gates.PANEL_COUNTS}
    assert 2*sum(counts[x] for x in r.admitted_panels(0))+6*sum(sum(counts[x] for x in r.admitted_panels(s)) for s in r.STAGES)==51648
    assert 2*len(r.ADMITTED)+6*sum(len(r.admitted_panels(s)) for s in r.STAGES)==204
    with pytest.raises(ValueError):r.admitted_panels(75)
