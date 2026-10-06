"""Private-profile provenance and import isolation; no tensor/model work."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import ModuleType
import time

import pytest

P = Path(__file__).resolve().parents[5]
PATH = P/'ipfs_datasets_py/logic/formalization/autoencoder/normative_wording_modality_auxiliary.py'
spec = importlib.util.spec_from_file_location('_normative_auxiliary_tests',PATH)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def fixture():
    rows = []
    refs = []
    for index in range(180):
        rule = dict(modality=('O','P','F')[index%3],actor=str(index),action='publish',object='notice')
        text = 'new authenticated text '+str(index)
        source_sha = hashlib.sha256(text.encode()).hexdigest()
        template = subject.TEMPLATES[index%2]
        rows.append(dict(id='clause:'+source_sha,source_text=text,source_sha256=source_sha,
            target=rule,template=template,parent_id='paragraph:'+str(index//8)))
        refs.append(dict(source_text=text,source_sha256=source_sha,template=template,
            target={'rules':[rule]},parent_paragraph_id='paragraph:'+str(index//8)))
    built = dict(source_rows=['sources'],references=['paragraphs'],clause_references=refs,
        receipt=dict(seed=20261006,sealed_recipe_sha256='a'*64))
    authored = ModuleType('_fake_authored')
    authored.TEMPLATES = subject.TEMPLATES
    authored.REQUIRED_PRIOR_DATASETS = ('legacy','new_sources')
    authored.build = lambda **kwargs:deepcopy(built)
    authored.sentence = lambda *args:'rendered'
    mixture = ModuleType('_fake_mixture')
    mixture.KEYS = {'policy','training_bank','prior_sources_by_dataset','corpus','source_plan',
        'source_inputs','production_report','evaluation_vectors_by_dataset','payload_sha256'}
    mixture.authored = 'original renderer'
    mixture.PRIOR_DATASETS = {'legacy'}
    exec('class Selector:\n'
        ' def __init__(self):\n  self.renderer=authored\n'
        ' @property\n def templates(self):\n  return authored.TEMPLATES\n',mixture.__dict__)
    helper = ModuleType('_fake_helper')
    helper.digest = digest
    helper.mixture = mixture
    helper.SCHEMA = 'old schema'
    helper.STRATA = ('old strata',)
    helper._rows = rows
    exec('def _deadline(deadline):\n return None\n'
        'def prepare_bank(*args, **kwargs):\n'
        ' inv=kwargs["source_inventory"]\n'
        ' assert set(inv)==mixture.KEYS\n'
        ' assert set(inv["prior_sources_by_dataset"])==mixture.PRIOR_DATASETS\n'
        ' assert inv["corpus"]==mixture.authored.build()\n'
        ' return {"schema":SCHEMA,"rows":_rows,"bank_sha256":"old"}\n'
        'def modality_loss(*args, **kwargs):\n return STRATA\n'
        'def prepare_tensor_cache(*args, **kwargs):\n return mixture.authored.sentence(None,None)\n',helper.__dict__)
    corpus = {key:deepcopy(built[key]) for key in ('source_rows','references','receipt')}
    inventory = dict(policy='original_only',training_bank=['original TRAIN'],
        prior_sources_by_dataset={'legacy':['old'],'new_sources':['new'],
            subject.FUTURE_SOURCE_INVENTORY:[dict(id='future:'+str(i),source_text='Future excluded source '+str(i)+'.')
                for i in range(60)]},corpus=corpus,
        source_plan='sealed',source_inputs='native cache',production_report='native report',
        evaluation_vectors_by_dataset={},clause_training_references=deepcopy(refs))
    inventory['payload_sha256'] = digest(inventory)
    configured = subject.configure(auxiliary_owner=helper,mixture_owner=mixture,authored_owner=authored)
    return helper,mixture,authored,configured,inventory


def prepare(owner, inventory):
    return owner.prepare_bank([],[],training_references=[],validation_references=[],
        source_contexts={},codec={},validate_rule=lambda value:{'valid':True},
        source_inventory=inventory,deadline=100.)


def test_profile_reuses_function_code_without_mutating_default_modules():
    helper,mixture,authored,configured,inventory = fixture()
    before = deepcopy(inventory)
    bank = prepare(configured,inventory)
    assert inventory == before
    assert helper.SCHEMA == 'old schema' and helper.STRATA == ('old strata',)
    assert helper.mixture is mixture and mixture.authored == 'original renderer'
    assert mixture.PRIOR_DATASETS == {'legacy'}
    assert configured.modality_loss.__code__ is helper.modality_loss.__code__
    assert configured.prepare_tensor_cache.__code__ is helper.prepare_tensor_cache.__code__
    assert configured.modality_loss.__globals__ is configured.__dict__
    assert configured.modality_loss() == subject.STRATA
    assert configured.prepare_tensor_cache() == 'rendered'
    selected = configured.mixture.Selector()
    assert selected.renderer is configured.mixture.authored
    assert selected.templates == subject.TEMPLATES
    assert mixture.Selector().renderer == 'original renderer'
    assert bank['schema'] == subject.SCHEMA and bank['source_inventory_sha256'] == inventory['payload_sha256']
    assert bank['bank_sha256'] == digest({k:v for k,v in bank.items() if k != 'bank_sha256'})
    assert bank['helper_defaults_modified'] is bank['package_aliases_modified'] is False


@pytest.mark.parametrize('mutation',['digest','unknown','missing','target','source','template','parent','partial'])
def test_bad_envelopes_or_clause_census_refuse(mutation):
    *_,owner,inventory = fixture()
    if mutation == 'digest':
        inventory['payload_sha256'] = 'wrong'
    else:
        if mutation == 'unknown':inventory['unknown'] = 'hidden'
        elif mutation == 'missing':inventory.pop('clause_training_references')
        elif mutation == 'partial':inventory['clause_training_references'].pop()
        else:inventory['clause_training_references'][0][mutation if mutation not in ('source','parent')
            else {'source':'source_text','parent':'parent_paragraph_id'}[mutation]] = 'changed'
        inventory['payload_sha256'] = digest({k:v for k,v in inventory.items() if k != 'payload_sha256'})
    with pytest.raises(ValueError):prepare(owner,inventory)


@pytest.mark.parametrize('mutation',['missing','partial','extra','label','text','duplicate','paragraph'])
def test_future_development_exclusions_are_bound_source_only_and_complete(mutation):
    *_,owner,inventory = fixture()
    prior = inventory['prior_sources_by_dataset']
    future = prior[subject.FUTURE_SOURCE_INVENTORY]
    if mutation == 'missing':prior.pop(subject.FUTURE_SOURCE_INVENTORY)
    elif mutation == 'partial':future.pop()
    elif mutation == 'extra':prior['unexpected'] = []
    elif mutation == 'label':future[0]['target_ids'] = [1,2]
    elif mutation == 'text':future[0]['source_text'] = 4
    elif mutation == 'duplicate':future[1] = deepcopy(future[0])
    else:future[0]['source_text'] = 'Two clauses.\n\nNot a single clause.'
    inventory['payload_sha256'] = digest({k:v for k,v in inventory.items() if k != 'payload_sha256'})
    with pytest.raises(ValueError):prepare(owner,inventory)


def test_wrong_template_profile_refused_before_any_bank_build():
    helper,mixture,authored,*_ = fixture()
    authored.TEMPLATES = ('old','old2')
    with pytest.raises(ValueError,match='two normative'):
        subject.configure(auxiliary_owner=helper,mixture_owner=mixture,authored_owner=authored)


def test_private_trainer_import_is_narrow_and_defaults_stay_unchanged():
    trainer = ModuleType('_fake_trainer')
    trainer.__package__ = 'ipfs_datasets_py.logic.formalization.autoencoder'
    seen = []
    original_import = lambda *args:seen.append(args) or ModuleType('_ordinary_import')
    trainer.__dict__['__builtins__'] = dict(__import__=original_import)
    exec('def train():\n from . import paraphrase_modality_auxiliary_training as owner\n return owner\n'
        'def ordinary():\n import math\n return math\n',trainer.__dict__)
    auxiliary = object()
    configured = subject.configure_trainer(trainer,auxiliary)
    assert configured.train() is auxiliary and seen == []
    assert configured.ordinary().__name__ == '_ordinary_import' and len(seen) == 1
    assert trainer.__dict__['__builtins__']['__import__'] is original_import
    assert configured.train.__code__ is trainer.train.__code__
    assert configured.train.__globals__ is configured.__dict__
    assert trainer.train.__globals__ is trainer.__dict__


def test_private_import_refuses_another_package():
    trainer = ModuleType('_fake_trainer')
    trainer.__package__ = 'ipfs_datasets_py.logic.formalization.autoencoder'
    exec('def train():\n return None\n',trainer.__dict__)
    configured = subject.configure_trainer(trainer,object())
    importer = configured.__dict__['__builtins__']['__import__']
    with pytest.raises(ValueError,match='escaped'):
        importer('',{'__package__':'different'},None,('paraphrase_modality_auxiliary_training',),1)


@pytest.mark.parametrize('dimension',[384,768])
def test_actual_unchanged_mixture_validator_and_selector_accept_new_renderings(monkeypatch,dimension):
    """Use synthetic vectors and a mocked native validator, with no model."""
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_training_mixture as mixture
    from ipfs_datasets_py.logic.formalization.autoencoder import normative_wording_training_sources as authored
    from ipfs_datasets_py.logic.formalization.autoencoder import paraphrase_modality_auxiliary_training as helper
    from .test_contextual_training_mixture import fixture as original_fixture
    train,dev,kw,_ = original_fixture(monkeypatch,dimension)
    old = kw.pop('mixture')
    prior = {name:[dict(id=f'exclusion:{name}:{i}',source_text=f'Distinct excluded {name} text {i}.')
        for i in range(count)] for name,count in authored.REQUIRED_PRIOR_COUNTS.items()}
    prior.update(original_train_bank=mixture._source_rows(old['training_bank']),
        raw_train=mixture._source_rows(old['training_bank']),paragraph_train=mixture._source_rows(train),
        paragraph_validation=mixture._source_rows(dev),r4_training_paraphrases=old['corpus']['source_rows'],
        prospective_development_sources=[dict(id='future:'+str(i),source_text='Prospective excluded source '+str(i)+'.')
            for i in range(60)])
    built = authored.build(training_bank=old['training_bank'],prior_sources_by_dataset=prior,
        codec=kw['codec'],sealed_recipe_sha256='a'*64,validate_rule=kw['validate_rule'])
    corpus = {key:built[key] for key in ('source_rows','references','receipt')}
    plan = mixture.producer.source_plan(corpus['source_rows'],
        expected_source_rows_sha256=corpus['receipt']['source_rows_sha256'],sealed_recipe_sha256='a'*64)
    vectors = {authored.text_sha(row['source_text']):[math.cos(5.+index*.0001),math.sin(5.+index*.0001)]+[0.]*(dimension-2)
        for index,row in enumerate(plan['shape_plan']['source_inputs'])}
    production = dict(dimension=dimension,production_sha256='b'*64,
        vectors=[dict(id=row['id'],source_sha256=authored.text_sha(row['source_text']),
            vector=vectors[authored.text_sha(row['source_text'])]) for row in plan['shape_plan']['source_inputs']])
    calls = []
    def native_validator(given_plan,given_report):
        assert given_plan == plan and given_report == production
        calls.append(1)
        return dimension
    monkeypatch.setattr(mixture.producer,'validate_report',native_validator)
    rows = [dict(row,input=vectors[authored.text_sha(row['source_text'])]) for row in corpus['source_rows']]
    cache = [dict(id='clause:'+ref['source_sha256'],source_text=ref['source_text'],
        input=vectors[ref['source_sha256']]) for ref in built['clause_references']]
    # The unchanged owner requires literal first occurrence order from paragraphs.
    ordered = {row['source_text']:row for row in cache}
    cache = [ordered[text] for row in corpus['source_rows'] for text in row['source_text'].split('\n\n')]
    contexts = mixture.context.build_source_contexts(corpus['source_rows'],cache)
    inputs = dict(schema='training-paraphrase-source-inputs/v1',complete=True,role='train_augmentation',
        dimension=dimension,rows=rows,clause_cache=cache,source_contexts=contexts,
        production_sha256='b'*64,source_plan_sha256=plan['plan_sha256'],targets_attached=False,
        preprocessing_fitted=False,qualified=False,admitted=False,checkpoint_promoted=False)
    inputs['inputs_sha256'] = mixture.digest(inputs)
    inventory = dict(policy='original_only',training_bank=old['training_bank'],prior_sources_by_dataset=prior,
        corpus=corpus,source_plan=plan,source_inputs=inputs,production_report=production,
        evaluation_vectors_by_dataset={name:[] for name in mixture.EVALUATION_DATASETS},
        clause_training_references=built['clause_references'])
    inventory['payload_sha256'] = mixture.digest(inventory)
    configured = subject.configure(auxiliary_owner=helper,mixture_owner=mixture,authored_owner=authored)
    result = configured.prepare_bank(train,dev,**kw,source_inventory=inventory,deadline=time.monotonic()+30.)
    assert calls == [1] and result['dimension'] == dimension and len(result['rows']) == 180
    assert {row['template'] for row in result['rows']} == set(subject.TEMPLATES)
    assert helper.STRATA != configured.STRATA and mixture.authored is not authored
