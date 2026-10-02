from pathlib import Path
import json
import pytest
from ipfs_datasets_py.logic.intent_ir.formalize import rich_aligned_decoder as d,rich_grammar as g


def test_fail_open_missing_checkpoint_and_unsupported_scope():
    report=d.prepare_aligned_rich_intent('Save cache')
    assert report['status']=='fail_open_no_checkpoint' and report['continue_planning']
    assert report['counts']=={'encoder_executions':0,'decoder_executions':0}
    assert d.prepare_aligned_rich_intent('```python\nprint(1)\n```')['status']=='fail_open_input_out_of_scope'


def test_closed_schema_mismatch_fails_open():
    report=d.prepare_aligned_rich_intent('Save cache',{'schema':'invented'})
    assert report['status']=='fail_open_checkpoint_or_inference_error'
    assert not report['source_agreement']


def test_actual_parent_forward_inverse_full_source_gate_and_replay():
    import torch
    torch.set_num_threads(1)
    root=Path(__file__).resolve().parents[7]
    path=root/'artifacts/ir-training-coverage-20261002/intent-01/source-run-receipt-02.json'
    if not path.exists():pytest.skip('local development checkpoint absent')
    descriptor=json.loads(path.read_bytes())['backend']
    instruction='Never create the API Brochure metrics under local storage.'
    report=d.prepare_aligned_rich_intent(instruction,descriptor,beam_width=16,project=False)
    assert report['rich_ir']['ast']==g.parse_instruction(instruction)
    assert report['counts']['encoder_executions']>0 and report['counts']['decoder_executions']>0
    assert report['learned']['encoder']['target_access'] is False and report['learned']['decoder']['target_access'] is False
    assert report['proof_authority'] is False
    d.validate_aligned_rich_intent(report,instruction=instruction,checkpoint_descriptor=descriptor)
    with pytest.raises(ValueError):d.validate_aligned_rich_intent(report,instruction=instruction.replace('Never','Must'),checkpoint_descriptor=descriptor)
