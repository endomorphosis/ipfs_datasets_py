"""CPU construction and complete decode controls using pinned retained fixtures.

No checkpoint is built or trained. The 4096 fixture is synthetic/untrained;
these controls grant no CUDA, native Leanstral, speed or proof qualification.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path('/home/barberb/lift_coding')
BASE = ROOT / 'artifacts/codebase_ir_terminal_bench'
FIXTURES = {
    768: ('native-768-device-qualification-20261004-04/diagnostic-native768-head.json',
          '9fcd8dd3b9727f5ee93b5b2cb2d7f23e482f16c24f64c23a3ae9da2168e3117b',
          'dimension-768-guard-cost-profile-20261004-03/dimension-inference-inputs.json',
          '1b29ffd8b62d628aa8d6823f5e5a2b702a710357add2f4337b6243b7ca117090'),
    4096: ('native-4096-synthetic-head-device-v2-qualification-20261004-04/synthetic-untrained-checkpoint.json',
           '04a8f2d317294861a7fcf9b6f156e915cd6c31bfa1482b8eaab4ecf15d00dee7',
           'dimension-4096-guard-cost-profile-20261004-04/dimension-inference-inputs.json',
           '2c4e4ac0053871c902c5aebb423ee2ccd1345fa46ad6c28234a45b10eaada388')}


def pinned(relative, expected):
    raw = (BASE / relative).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    return json.loads(raw)


@pytest.fixture(scope='module')
def tools():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_cached_input_device_inference as api
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
    assert torch.get_num_threads() == 1 and not torch.cuda.is_available()
    path = ROOT / 'external/ipfs_datasets/benchmarks/qualify_bitwise_trained_head_devices.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '29720e69e03eeaa6a5bb62e74bc5ae1fdd8a3da5661d17c767df9cc04099f110'
    spec = importlib.util.spec_from_file_location('cached_span_portable_comparison', path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return torch, api, resources, helper


@pytest.mark.parametrize('dimension', [768, 4096])
@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('count', [1, 16, 32])
def test_full_cpu_session_construction_and_complete_decodes(tools, tmp_path, dimension, optimized, count):
    torch, api, resources, helper = tools
    cp_path, cp_sha, inputs_path, inputs_sha = FIXTURES[dimension]
    checkpoint, inputs = pinned(cp_path, cp_sha), pinned(inputs_path, inputs_sha)
    scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(
        state_path=tmp_path/'local-scheduler.json', total_cpu_slots=2, total_memory_mb=2048,
        total_gpu_memory_mb=256, total_unified_memory_mb=2048, lane_reservations={},
        auto_renew_leases=False, resource_pressure_sampler=lambda: {
            'gpu_telemetry_available': True, 'cuda_available': False, 'gpu_device_count': 0,
            'gpu_memory_percent': 0.}))
    base, candidate = ((api._BASE_768, api.InputCachedDeviceDimensionalSpanSession) if dimension == 768 else
                       (api._BASE_4096, api.InputCachedDeviceLeanstral4096SpanSession))
    options = {'expected_checkpoint_sha256': cp_sha, 'optimized': optimized, 'scheduler': scheduler,
               'admission_timeout_seconds': 2, 'max_seconds': 30, 'memory_mb': 1024, 'gpu_memory_mb': 256}
    if dimension == 4096:
        options['synthetic_unreceipted'] = True
    kwargs = ({} if dimension == 4096 else {'embedding_receipts': deepcopy(inputs['receipts'][:count]),
              'expected_receipt_sha256s': inputs['receipt_pins'][:count]})
    reports, profiles, state_pins = [], [], []
    for cls in (base, candidate):
        with cls(deepcopy(checkpoint), **options) as owner:
            assert owner._device == 'cpu'
            profiles.append(owner.describe())
            before = helper._state_pin(owner, 'span')
            rng = torch.get_rng_state().clone()
            report = owner.decode_formal_logic(deepcopy(inputs['texts'][:count]),
                                               deepcopy(inputs['vectors'][:count]), **deepcopy(kwargs))
            assert torch.equal(rng, torch.get_rng_state())
            assert helper._state_pin(owner, 'span') == before
            assert owner._checkpoint == checkpoint
            assert len(report['rows']) == count
            reports.append(report)
            state_pins.append(before)
        assert owner._lease.released and owner._closed
    assert state_pins[0] == state_pins[1]
    assert helper._decisions(reports[0], 'span') == helper._decisions(reports[1], 'span')
    assert profiles[1]['cached_input_implementation']['existing_selected_route_changed'] is False
    if optimized:
        assert profiles[1]['profile_id'] == (api.PROFILE_768 if dimension == 768 else api.PROFILE_4096)
    else:
        assert profiles[1]['profile_id'] == profiles[0]['profile_id']
    snapshot = scheduler.snapshot()
    assert snapshot['allocated'] == {'cpu_slots': 0, 'memory_mb': 0}
    assert snapshot['active_lease_count'] == snapshot['waiting_request_count'] == 0
