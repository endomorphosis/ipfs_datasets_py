"""Authored CFG fixtures; symbolic walks do not establish Python execution."""
from __future__ import annotations

from collections import Counter
import copy
from dataclasses import replace
import hashlib

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_source as v1, numerical_source_v2 as v2
from ipfs_datasets_py.logic.software_verification.numerical_source_v3 import (
    PROFILE, adapt_numerical_source, validate_control_structure, verify_numerical_source,
)


def _one(source):
    result=adapt_numerical_source(source)
    assert result.status=="translated"
    assert validate_control_structure(result.program,result.guarded_regions,result.control_regions,result.command_contexts)
    return result


def _maps(result):
    return ({e.expression_id:e for e in result.program.expressions},
            {c.command_id:c for c in result.program.commands})


def _walk(result, decisions=None):
    """Walk chosen abstract outcomes, never evaluate a source expression."""
    decisions={k:list(v) for k,v in (decisions or {}).items()}
    cfg=result.program.functions[0].cfg;blocks={b.block_id:b for b in cfg.blocks}
    current,trace=cfg.entry_block_id,[]
    for _ in range(300):
        trace.extend(blocks[current].command_ids)
        outgoing=[e for e in cfg.edges if e.source_block_id==current]
        if not outgoing:return trace,current
        choice=decisions[current].pop(0) if current in decisions and decisions[current] else None
        candidates=[e for e in outgoing if (e.kind.value,e.exception_type)==choice] if choice else [e for e in outgoing if e.kind.value in {"normal","return","break","continue"}]
        assert len(candidates)==1,(current,choice)
        current=candidates[0].target_block_id
    raise AssertionError("bounded symbolic walk did not exit")


def test_for_protocol_uses_slots_and_only_advance_exhaustion():
    r=_one("def scan(values):\n    for item in values():\n        consume(item)\n    else:\n        done()\n    return item\n")
    loop=r.control_regions[0];expr,commands=_maps(r)
    assert loop['kind']=='for_statement'
    init=expr[loop['iterator_expression_id']];advance=expr[loop['advance_expression_id']]
    assert init.operand_ids==(loop['iterable_expression_id'],)
    assert expr[advance.operand_ids[0]].symbol_ids==(loop['iterator_symbol_id'],)
    target=commands[loop['target_command_id']]
    assert expr[target.expression_ids[0]].symbol_ids==(loop['item_symbol_id'],)
    assert target.target_symbol_ids==(loop['target_symbol_id'],)
    assert init.expression_id not in advance.operand_ids
    assert advance.expression_id not in target.expression_ids
    cfg=r.program.functions[0].cfg;edges={e.edge_id:e for e in cfg.edges}
    exhaustion=edges[loop['exhaustion_edge_id']]
    assert exhaustion.exception_type=='StopIteration' and exhaustion.target_block_id==loop['else_entry_block_id']
    assert {e.edge_id for e in cfg.edges if e.exception_type=='StopIteration'}=={exhaustion.edge_id}
    assert edges[loop['other_exception_edge_id']].order>exhaustion.order
    assert loop['exception_dispatch']['other_exception_excludes']==['StopIteration']
    assert loop['target_may_be_unbound_after_zero_iterations'] is True
    assert loop['implicit_iterator_close_claimed'] is False


@pytest.mark.parametrize('iterations',[0,1,3])
def test_symbolic_for_walk_initializes_once_advances_per_attempt_and_binds_per_yield(iterations):
    r=_one("def scan(values):\n    for item in values():\n        consume(item)\n    else:\n        done()\n")
    loop=r.control_regions[0]
    trace,exit_block=_walk(r,{loop['header_block_id']:[('normal','')]*iterations+[('exception','StopIteration')]})
    counts=Counter(trace)
    assert counts[loop['iterator_command_id']]==1
    assert counts[loop['advance_command_id']]==iterations+1
    assert counts[loop['target_command_id']]==iterations
    body=[c['command_id'] for c in r.command_contexts if c['loop_contexts'] and c['loop_contexts'][-1]['phase']=='body']
    otherwise=[c['command_id'] for c in r.command_contexts if c['loop_contexts'] and c['loop_contexts'][-1]['phase']=='else']
    assert all(counts[c]==iterations for c in body)
    assert all(counts[c]==1 for c in otherwise)
    assert exit_block in r.program.functions[0].cfg.normal_exit_block_ids


def test_nested_iterable_initialization_is_once_per_activation_not_per_function():
    r=_one("def scan(outer_values, inner_values):\n    for outer in outer_values():\n        for inner in inner_values():\n            consume(outer, inner)\n")
    outer,inner=r.control_regions
    trace,_=_walk(r,{outer['header_block_id']:[('normal',''),('normal',''),('exception','StopIteration')],
                    inner['header_block_id']:[('normal',''),('exception','StopIteration')]*2})
    counts=Counter(trace)
    assert counts[outer['iterator_command_id']]==1
    assert counts[inner['iterator_command_id']]==2
    assert counts[inner['advance_command_id']]==4
    context=next(c for c in r.command_contexts if c['command_id']==inner['iterator_command_id'])
    assert [x['phase'] for x in context['loop_contexts']]==['body','initialize']
    assert context['loop_contexts'][0]['iteration_variable'] is not None
    assert context['loop_contexts'][1]['iteration_variable'] is None


@pytest.mark.parametrize('phase',['initialize','advance','target','body','else'])
def test_non_exhaustion_failures_take_exceptional_exit_and_skip_later_work(phase):
    r=_one("def scan(values):\n    for item in values():\n        consume(item)\n    else:\n        done()\n    after()\n")
    loop=r.control_regions[0]
    context=next(c for c in r.command_contexts if c['loop_contexts'] and c['loop_contexts'][-1]['phase']==phase)
    decisions={}
    if phase not in {'initialize','advance'}:
        decisions[loop['header_block_id']]=[('exception','StopIteration')] if phase=='else' else [('normal','')]
    decisions[context['block_id']]=[('exception','BaseException')]
    trace,last=_walk(r,decisions)
    assert last in r.program.functions[0].cfg.exceptional_exit_block_ids
    later=[c['command_id'] for c in r.command_contexts if not c['loop_contexts']]
    assert not set(trace)&set(later)
    if phase!='else':
        else_commands={c['command_id'] for c in r.command_contexts if c['loop_contexts'] and c['loop_contexts'][-1]['phase']=='else'}
        assert not set(trace)&else_commands


@pytest.mark.parametrize('kind',['for','while'])
def test_break_bypasses_else_and_continue_revisits_correct_header(kind):
    header='for item in values' if kind=='for' else 'while ready()'
    r=_one('def scan(values):\n    '+header+':\n        if skip():\n            continue\n        break\n    else:\n        done()\n    after()\n')
    loop=next(x for x in r.control_regions if x['kind']!= 'if_statement')
    branch=next(x for x in r.control_regions if x['kind']=='if_statement')
    trace,_=_walk(r,{loop['header_block_id']:[('normal','') if kind=='for' else ('true','')]*2,
                     branch['header_block_id']:[('true',''),('false','')]})
    contexts={c['command_id']:c for c in r.command_contexts}
    assert sum(contexts[c]['control_transfer']=='continue' for c in trace)==1
    assert sum(contexts[c]['control_transfer']=='break' for c in trace)==1
    assert not any(contexts[c]['loop_contexts'] and contexts[c]['loop_contexts'][-1]['phase']=='else' for c in trace)
    assert loop['break_edge_ids'] and loop['continue_edge_ids']


@pytest.mark.parametrize('transfer',['break','continue'])
def test_inner_loop_else_transfer_targets_outer_loop(transfer):
    r=_one('def f(values):\n    for outer in values:\n        for inner in values:\n            pass\n        else:\n            '+transfer+'\n    return values\n')
    outer,inner=r.control_regions
    context=next(c for c in r.command_contexts if c['control_transfer']==transfer)
    assert context['target_region_id']==outer['region_id']
    assert [x['phase'] for x in context['loop_contexts']]==['body','else']
    assert context['loop_contexts'][-1]['iteration_variable'] is None
    assert context['loop_contexts'][-1]['occurrence']=='exhausted_activation'
    assert not inner[transfer+'_edge_ids'] and outer[transfer+'_edge_ids']


@pytest.mark.parametrize('transfer',['break','continue'])
def test_loop_else_transfer_without_outer_loop_is_fenced(transfer):
    # ast.parse accepts this; Python compilation rejects it. No source code is
    # compiled/executed here: the frontend independently refuses the transfer.
    r=adapt_numerical_source('def f(values):\n    for item in values:\n        pass\n    else:\n        '+transfer+'\n')
    assert r.status=='partial'
    assert 'python.transfer.no_enclosing_loop' in {d['code'] for d in r.diagnostics}
    assert not any(c['control_transfer']==transfer for c in r.command_contexts)


@pytest.mark.parametrize('iterations',[0,2])
def test_while_repeats_test_and_else_has_no_body_iteration(iterations):
    r=_one('def f():\n    while test():\n        work()\n    else:\n        done()\n')
    loop=r.control_regions[0]
    trace,_=_walk(r,{loop['header_block_id']:[('true','')]*iterations+[('false','')]})
    counts=Counter(trace)
    assert counts[loop['test_command_id']]==iterations+1
    assert loop['edge_conditions_reference_evaluated_values'] is True
    edges=[e for e in r.program.functions[0].cfg.edges if e.source_block_id==loop['header_block_id'] and e.kind.value in {'true','false'}]
    assert {e.condition_expression_id for e in edges}=={loop['test_expression_id']}
    else_context=next(c for c in r.command_contexts if c['loop_contexts'][-1]['phase']=='else')
    assert else_context['loop_contexts'][-1]['iteration_variable'] is None


def test_return_inside_loop_bypasses_else_and_function_continuation():
    r=_one('def f(values):\n    for item in values:\n        return result(item)\n    else:\n        done()\n    after()\n')
    loop=r.control_regions[0]
    trace,last=_walk(r,{loop['header_block_id']:[('normal','')]})
    contexts={c['command_id']:c for c in r.command_contexts}
    assert contexts[trace[-1]]['control_transfer']=='return'
    assert last in r.program.functions[0].cfg.normal_exit_block_ids
    assert all(contexts[c]['loop_contexts'][-1]['phase']!='else' for c in trace)


def test_both_if_branches_return_without_fabricating_reachable_join():
    r=_one('def f(flag):\n    if flag():\n        return left()\n    else:\n        return right()\n')
    branch=r.control_regions[0]
    assert branch['continuation_block_id'] is None
    for outcome in ('true','false'):
        trace,last=_walk(r,{branch['header_block_id']:[(outcome,'')]})
        assert len(trace)==2 and last in r.program.functions[0].cfg.normal_exit_block_ids


@pytest.mark.parametrize('header',['for value in values','while test()'])
def test_loop_body_and_else_can_both_return_without_reachable_continuation(header):
    r=_one('def f(values):\n    '+header+':\n        return selected()\n    else:\n        return empty()\n')
    loop=r.control_regions[0]
    assert loop['continuation_block_id'] is None
    outcomes=[('normal',''),('exception','StopIteration')] if header.startswith('for') else [('true',''),('false','')]
    contexts={c['command_id']:c for c in r.command_contexts}
    for outcome in outcomes:
        trace,last=_walk(r,{loop['header_block_id']:[outcome]})
        assert contexts[trace[-1]]['control_transfer']=='return'
        assert last in r.program.functions[0].cfg.normal_exit_block_ids


@pytest.mark.parametrize('header',['if test()','while test()'])
@pytest.mark.parametrize('mutation',['swap_branches','different_condition','exception_to_normal_exit'])
def test_direct_cfg_mutation_cannot_change_cached_header_test_contract(header,mutation):
    r=_one('def f():\n    '+header+':\n        return selected()\n    else:\n        return other()\n')
    region=r.control_regions[0];function=r.program.functions[0];expr,_=_maps(r)
    changed=[]
    for edge in function.cfg.edges:
        if edge.source_block_id==region['header_block_id']:
            if mutation=='swap_branches' and edge.kind.value in {'true','false'}:
                edge=replace(edge,target_block_id=region['else_entry_block_id'] if edge.kind.value=='true' else region['body_entry_block_id'])
            elif mutation=='different_condition' and edge.kind.value in {'true','false'}:
                edge=replace(edge,condition_expression_id=expr[region['test_expression_id']].operand_ids[0])
            elif mutation=='exception_to_normal_exit' and edge.kind.value=='exception':
                edge=replace(edge,target_block_id=function.cfg.normal_exit_block_ids[0])
        changed.append(edge)
    program=replace(r.program,program_id='',functions=(replace(function,cfg=replace(function.cfg,edges=tuple(changed))),))
    with pytest.raises(ValueError,match='cached-value contract'):
        validate_control_structure(program,r.guarded_regions,r.control_regions,r.command_contexts)


def test_guarded_expressions_and_messages_retain_loop_occurrence_context():
    r=_one('def f(values, flag):\n    for value in values:\n        assert value if flag else fallback(), f"bad {value!r:{width()}}"\n')
    assert len(r.guarded_regions)==2
    assertion=next(c for c in r.program.commands if c.kind.value=='assert')
    context=next(c for c in r.command_contexts if c['command_id']==assertion.command_id)
    assert context['loop_contexts'][-1]['phase']=='body'
    assert len(assertion.expression_ids)==1


@pytest.mark.parametrize('construct',[
    'for left, right in values:\n        hidden(left)',
    'for owner.field in values:\n        hidden(owner)',
    'try:\n        hidden()\n    except Exception:\n        pass',
    'with resource():\n        hidden()',
    'async for value in values:\n        hidden(value)',
])
def test_unreviewed_constructs_remain_fences_without_flattening(construct):
    r=adapt_numerical_source('def f(values):\n    '+construct+'\n')
    assert r.status=='partial'
    assert not r.control_regions
    assert not any(e.attributes.get('qualified_callee')=='hidden' for e in r.program.expressions)
    assert any(c.attributes.get('body_not_linearized') for c in r.program.commands)


@pytest.mark.parametrize('rhs',['left() if flag else right()','(left() if flag else right()) + (lambda: flag)'])
def test_unsupported_assignment_drops_orphan_guarded_rhs_but_retains_fence_context(rhs):
    r=adapt_numerical_source('def f(values, flag):\n    for value in values:\n        owner.field = '+rhs+'\n')
    assert r.status=='partial'
    assert not r.guarded_regions
    assert len(r.control_regions)==1
    assert not any(e.attributes.get('qualified_callee') in {'left','right'} for e in r.program.expressions)
    assert validate_control_structure(r.program,r.guarded_regions,r.control_regions,r.command_contexts)


@pytest.mark.parametrize('newline',['\n','\r\n','\r'])
def test_raw_utf8_source_mapping_and_no_target_execution(tmp_path,newline):
    marker=tmp_path/'not-created'
    source=newline.join(['# λ','def f(values):','    for value in values:',f'        open({str(marker)!r}, "w")',''])
    r=_one(source)
    assert not marker.exists()
    assert r.source_sha256==hashlib.sha256(source.encode()).hexdigest()
    assert all(0<=s.start_byte<=s.end_byte<=len(source.encode()) for s in r.program.spans)
    assert verify_numerical_source(r,source).to_dict()==r.to_dict()


def test_previous_profiles_retain_exact_artifacts_and_do_not_gain_loop_admission():
    source='def f(values):\n    for value in values:\n        use(value)\n'
    old1=v1.adapt_numerical_source(source).to_dict();old2=v2.adapt_numerical_source(source).to_dict()
    r=_one(source)
    assert v1.adapt_numerical_source(source).to_dict()==old1
    assert v2.adapt_numerical_source(source).to_dict()==old2
    assert old1['status']==old2['status']=='partial'
    wire=r.to_dict()
    assert wire['profile']==PROFILE and wire['control_extension_required'] is True
    assert wire['standalone_program_evaluation_complete'] is False
    for key in ['proof_authority','source_semantics_verified','termination_verified','loop_invariants_verified','definite_assignment_verified']:
        assert wire[key] is False


@pytest.mark.parametrize('mutation',['exhaustion_else','exhaustion_priority','state_slot','loop_frequency','authority','missing_context','wrong_context','transfer_target','test_reexecution'])
def test_control_validator_rejects_broken_protocol_ownership_and_guards(mutation):
    r=_one('def f(values):\n    for item in values:\n        if check(item):\n            continue\n        break\n    else:\n        done()\n')
    regions=copy.deepcopy(list(r.control_regions));contexts=copy.deepcopy(list(r.command_contexts));loop=regions[0]
    if mutation=='exhaustion_else':loop['else_entry_block_id']=loop['body_entry_block_id']
    elif mutation=='exhaustion_priority':loop['exception_dispatch']['exhaustion_edge_precedes_other_exception']=False
    elif mutation=='state_slot':loop['item_symbol_id']=loop['iterator_symbol_id']
    elif mutation=='loop_frequency':loop['evaluation_policy']='initialize_globally_once'
    elif mutation=='authority':loop['termination_status']='proved'
    elif mutation=='missing_context':contexts.pop()
    elif mutation=='wrong_context':contexts[0]['loop_contexts'][0]['iteration_variable']='fabricated:0'
    elif mutation=='transfer_target':next(c for c in contexts if c['control_transfer']=='break')['target_region_id']=regions[1]['region_id']
    else:regions[1]['edge_conditions_reference_evaluated_values']=False
    with pytest.raises(ValueError):validate_control_structure(r.program,r.guarded_regions,regions,contexts)


@pytest.mark.parametrize('mutation',['region','context','graph','source','authority'])
def test_exact_source_replay_rejects_modified_control_claims(mutation):
    source='def f(values):\n    for value in values:\n        consume(value)\n'
    r=_one(source);wire=r.to_dict()
    if mutation=='region':wire['control_regions'][0]['target_may_be_unbound_after_zero_iterations']=False
    elif mutation=='context':wire['command_contexts'][0]['reachability_verified']=True
    elif mutation=='graph':wire['program']['functions'][0]['cfg']['edges'][0]['kind']='continue'
    elif mutation=='source':source+='\n'
    else:wire['proof_authority']=True
    with pytest.raises(ValueError,match='exact replay'):verify_numerical_source(wire,source)


@pytest.mark.parametrize('source',['',' '*65537,'\ud800'])
def test_source_bounds_preserved(source):
    with pytest.raises(ValueError):adapt_numerical_source(source)


@pytest.mark.parametrize('bound',['MAX_BLOCKS','MAX_EDGES'])
def test_cfg_resource_bounds_are_enforced_without_execution(monkeypatch,bound):
    from ipfs_datasets_py.logic.software_verification import numerical_source_v3 as frontend
    monkeypatch.setattr(frontend,bound,3 if bound=='MAX_BLOCKS' else 1)
    with pytest.raises(ValueError,match='bound exceeded'):
        frontend.adapt_numerical_source('def f(values):\n    for item in values:\n        use(item)\n')


def test_syntax_abstention_and_pure_function_without_exception_exit():
    assert adapt_numerical_source('def :').status=='unsupported'
    r=_one('def f():\n    pass\n')
    assert not r.program.functions[0].cfg.exceptional_exit_block_ids
