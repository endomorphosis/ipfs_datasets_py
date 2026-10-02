"""Closed source-bound8D requests refuse before loading the numerical runtime."""
import builtins

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_feature_worker as worker


@pytest.mark.parametrize('value',[None,[],{},dict(schema='wrong'),dict(schema=worker.SCHEMA,authority=True)])
def test_invalid_envelope_refuses_before_torch(value,monkeypatch):
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name=='torch' or name.startswith('torch.'):pytest.fail('invalid envelope loaded Torch')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    with pytest.raises(ValueError,match='closed'):
        worker.execute(value)


def test_unknown_action_refuses_before_torch(monkeypatch):
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name=='torch' or name.startswith('torch.'):pytest.fail('invalid action loaded Torch')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    request={name:None for name in ('contract','feature_space','base_state','training_targets',
        'tuning_targets','canary_targets','replay_targets','epochs','learning_rate','seed','max_seconds')}
    request.update(schema=worker.SCHEMA,action='gradient_fallback')
    with pytest.raises(ValueError,match='unknown native worker action'):
        worker.execute(request)
