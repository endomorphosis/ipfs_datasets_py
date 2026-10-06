"""Fixed matched recipe, pinned donor and pure sampler controls."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

P = Path(__file__).resolve().parents[5]
PATH = P/'scripts/ops/autoencoder/benchmark_normative_wording_training.py'
spec = importlib.util.spec_from_file_location('_normative_training_runner_tests',PATH)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@pytest.mark.parametrize('key,value',[('context_tokens',1024),('temperature',1),('max_target_tokens',1024),
    ('full_vocabulary_size',3),('optimizer_steps_per_fit',340),('learning_rate',.001),
    ('source_training_mixture_enabled',True),('preprocessing_refitted',True),('selection_unchanged',False),
    ('private_renderer_profile',False),('package_aliases_modified',True),
    ('previous_development_targets_used_for_training',True),('zero_arm_exact_m2_zero_replay',False),
    ('bridge_names',['modal_frame_logic']),('legal_ir_evaluate_provers',True)])
def test_fixed_recipe_refuses_budget_or_authority_changes(key,value):
    plan = deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[key] = value
    with pytest.raises(ValueError,match='recipe differs'):subject.validate_plan(plan)


def test_configured_m2_owner_keeps_original_recipe_and_fit_code():
    original = subject.load_base(P/subject.BASE_FILE)
    configured = subject.load_training_owner()
    assert original.FIXED['schema'] == 'paraphrase-modality-training-plan/v1'
    assert original.ARMS[0]['name'] == 'paraphrase-modality-zero'
    assert configured.FIXED is subject.FIXED and configured.ARMS == subject.ARMS
    assert configured.train_candidate.__code__.co_code == original.train_candidate.__code__.co_code
    assert configured.validate_zero_replay.__code__.co_code == original.validate_zero_replay.__code__.co_code


def test_pin_failure_precedes_donor_import(tmp_path):
    path = tmp_path/'wrong.py'
    path.write_text('raise RuntimeError("must not run")\n')
    with pytest.raises(ValueError,match='pin differs'):subject.load_base(path)


def test_new_auxiliary_strata_keep_six_balanced_streams_without_rng_work():
    owner = subject.load_training_owner()
    rows = []
    for modality in ('O','P','F'):
        for template in subject.TEMPLATES:
            for index in range(30):
                text = f'{modality}:{template}:{index}'
                sha = hashlib.sha256(text.encode()).hexdigest()
                rows.append(dict(id='clause:'+sha,source_sha256=sha,modality=modality,template=template,
                    modality_token_id={'O':4,'P':5,'F':3}[modality]))
    rows.sort(key=lambda row:row['id'])
    value = owner.schedule(dict(rows=rows,bank_sha256='sealed'),digest)
    assert len(value['draws']) == 170 and value['row_presentations'] == 1020
    assert Counter(value['per_source_exposures'].values()) == {6:120,5:60}
    assert all(draw['target_token_ids'] == [4,4,5,5,3,3] for draw in value['draws'])
    assert value['per_modality_presentations'] == dict(O=340,P=340,F=340)


def test_all_diagnostic_flags_remain_false():
    owner = subject.load_training_owner()
    assert all(value is False for value in owner.FALSE.values())
    assert subject.FIXED['context_tokens'] == subject.FIXED['max_target_tokens'] == 512
    assert subject.FIXED['bridge_names'] == [] and not subject.FIXED['encoder_executed']
