"""The throughput CLI cannot prepare/evaluate the authored heldout partition."""
import importlib.util
from pathlib import Path
import pytest

p=Path(__file__).resolve().parents[3]/'scripts/ops/autoencoder/benchmark_domain_training_throughput.py'
spec=importlib.util.spec_from_file_location('benchmark_domain_speed',p)
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)


def test_preparation_boundary_opens_only_train_tuning(monkeypatch):
    calls=[]
    def prepare(domain,split):
        assert split in ('train','validation'), 'heldout target opened'
        calls.append((domain,split))
        return [{'partition':split}]
    monkeypatch.setattr(api.panel,'prepare_partition',prepare)
    for domain in api.panel.DOMAINS:
        targets=api.development_targets(domain)
        assert set(targets)=={'training','validation'}
    assert calls==[(domain,split) for domain in api.panel.DOMAINS for split in ('train','validation')]


@pytest.mark.parametrize('kwargs',[
    {'domains':['intent_ir','intent_ir']},{'domains':['unknown']},{'domains':[]},
    {'epochs':0},{'epochs':257},{'epochs':True},{'repetitions':0},{'repetitions':8},
    {'minibatch_size':0},{'minibatch_size':1025}])
def test_bad_configuration_never_opens_targets(tmp_path,monkeypatch,kwargs):
    def never(*args,**kwargs): pytest.fail('invalid configuration opened targets')
    monkeypatch.setattr(api.panel,'prepare_partition',never)
    with pytest.raises(ValueError): api.run(tmp_path/'out',**kwargs)
    assert not (tmp_path/'out').exists()


def test_missing_startup_caps_never_opens_targets(tmp_path,monkeypatch):
    monkeypatch.delenv('OMP_NUM_THREADS',raising=False)
    monkeypatch.setattr(api.panel,'prepare_partition',lambda *args:pytest.fail('opened target before environment validation'))
    with pytest.raises(ValueError,match='startup thread caps'): api.run(tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_coverage_counts_actual_ready_targets_only():
    reports=[{'requested_families':['fol','tdfol','dcec'],'projections':[
        {'projection_id':'fol:native','logic_family':'fol','ready_for_training':True},
        {'projection_id':'dcec:missing','logic_family':'dcec','ready_for_training':False}]}]
    value=api._coverage({'training':reports,'validation':reports})
    assert value['requested_family_count']==3
    assert value['ready_family_ids']==['fol']
    assert value['ready_projection_count']==1
