"""The speed comparison cannot pass a zero-update or altered-loss run."""
import importlib.util
from pathlib import Path
import pytest

p=Path(__file__).resolve().parents[3]/'scripts/ops/legal_ir/benchmark_prepared_family_training.py'
spec=importlib.util.spec_from_file_location('benchmark_prepared_family',p)
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)


def test_no_update_is_not_parity():
    with pytest.raises(ValueError,match='actual optimizer'):
        api.require_exact({'report':{'optimizer_steps':0}},{'report':{'optimizer_steps':0}})


def test_changed_history_is_not_parity():
    with pytest.raises(ValueError,match='history differs'):
        api.require_exact({'report':{'optimizer_steps':1,'history':[.1]}},
                          {'report':{'optimizer_steps':1,'history':[.2]}})


def test_primary_throughput_includes_full_call():
    rows=[{'reference':{'wall_seconds':2.,'optimizer_row_presentations':12,'optimizer_steps':2}},
          {'reference':{'wall_seconds':4.,'optimizer_row_presentations':12,'optimizer_steps':2}}]
    result=api.summarize(rows,'reference')
    assert result['optimizer_row_presentations_per_second']==4.
    assert result['optimizer_steps_per_second']==pytest.approx(2/3)


def test_startup_thread_caps_required(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENBLAS_NUM_THREADS','9')
    with pytest.raises(ValueError,match='startup environment'):
        api.run(tmp_path/'missing','x',tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_input_sha_and_closed_training_split_before_output(tmp_path,monkeypatch):
    for key,value in {'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}.items():
        monkeypatch.setenv(key,value)
    p=tmp_path/'input.json';p.write_bytes(b'{"heldout": []}')
    with pytest.raises(ValueError,match='input digest'):
        api.run(p,'wrong',tmp_path/'out')
    with pytest.raises(ValueError,match='only explicit'):
        api.run(p,api.digest(p.read_bytes()),tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_last_epoch_patience_is_still_complete_budget():
    api.require_budget({'epochs_completed':256,'optimizer_steps':1024,'stopping':'validation_patience'},256,24,6)
    with pytest.raises(ValueError,match='identical update budget'):
        api.require_budget({'epochs_completed':256,'optimizer_steps':1023,'stopping':'validation_patience'},256,24,6)
    with pytest.raises(ValueError,match='identical update budget'):
        api.require_budget({'epochs_completed':255,'optimizer_steps':1020,'stopping':'validation_patience'},256,24,6)
