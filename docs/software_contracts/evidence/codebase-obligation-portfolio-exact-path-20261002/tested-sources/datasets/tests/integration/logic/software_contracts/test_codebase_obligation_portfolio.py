"""Native six-family qualification, distinct from explicitly injected controls."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_scan_policy import CodebaseScanPolicy, prepare_policy_current
from ipfs_datasets_py.logic.software_contracts.codebase_semantic_manifest import build_codebase_semantic_manifest
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract, compile_integer_offset
from ipfs_datasets_py.logic.software_contracts.codebase_family_lowering import CodebaseFamilyBundle, CodebaseFamilyError
from ipfs_datasets_py.logic.software_contracts.codebase_family_execution import seal_family_tools, validate_family_tools, BACKENDS
from ipfs_datasets_py.logic.software_contracts.codebase_obligation_graph import build_codebase_obligation_plans
from ipfs_accelerate_py.agent_supervisor.runtime.repository_resource_bridge import (
    RepositoryResourceBridge,RepositoryResourceBudget,RepositoryPhaseDemand,
)
from ipfs_accelerate_py.agent_supervisor.runtime.resource_scheduler import ResourceScheduler,ResourcePolicy
from ipfs_accelerate_py.agent_supervisor.proof import codebase_obligation_portfolio as module


def bundle(offset=1,contract=1,path='main.py'):
    return CodebaseFamilyBundle(compile_integer_offset(
        ('def increment(n: int) -> int:\n    return n + '+str(offset)+'\n').encode(),
        IntegerOffsetContract(path,'increment','n',contract),revision='pure-control'),(-1,0,1))


def native_tools():
    root=Path.home()/'.local/share/ipfs_datasets_py/theorem-provers'
    java=root/'Isabelle2025-2-linux-aarch64/Isabelle2025-2/contrib/jdk-21.0.9/arm64-linux/bin/java'
    return seal_family_tools(dict(lean=str(Path.home()/'.elan/toolchains/leanprover--lean4---v4.34.1/bin/lean'),
        rocq=str(root/'bin/coqtop'),isabelle=str(root/'bin/isabelle'),
        z3=str(Path.home()/'.local/bin/z3'),cvc5=str(Path.home()/'.local/bin/cvc5'),tlc=str(root/'bin/tlc'),java=str(java)),
        runtime_artifacts={'tlc':[root/'tlc/1.8.0/tla2tools.jar',java],
            'rocq':[root/'opam/ipfs-datasets-coq/bin/rocq'],
            'isabelle':[root/'Isabelle2025-2-linux-aarch64/Isabelle2025-2/bin/isabelle']})


@pytest.fixture
def repository(tmp_path,monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_GLOBAL','/dev/null');monkeypatch.setenv('GIT_CONFIG_NOSYSTEM','1')
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'xdg'))
    root=tmp_path/'repository';root.mkdir()
    subprocess.run(['git','init','-q',str(root)],check=True)
    (root/'main.py').write_text('def increment(n: int) -> int:\n    return n + 1\n')
    (root/'second.py').write_text('def increment(n: int) -> int:\n    return n + 2\n')
    (root/'README.txt').write_text('Inventory frontier retained.\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Portfolio fixture','-c','user.email=fixture@example.invalid',
                    'commit','-qm','captured native portfolio inputs'],check=True)
    connection=duckdb.connect(str(tmp_path/'catalog.duckdb'),config={'threads':1,'memory_limit':'64MB'})
    store=DuckDBASTStore(connection=connection);cas=ImmutableCAS(tmp_path/'cas')
    index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
    with RepositoryResourceBridge(ResourceScheduler(ResourcePolicy(max_lanes=8))).reserve(repository_id='portfolio:fixture',
            workspace=tmp_path,budget=RepositoryResourceBudget(cpu_slots=2,memory_mb=2048,process_slots=2,wall_time_ms=300000)) as parent:
        with parent.phase(RepositoryPhaseDemand('scan')) as phase:
            policy=prepare_policy_current(index,root,repository_id='portfolio:fixture',operation_id='capture',
                expected_head=None,policy=CodebaseScanPolicy(max_file_bytes=512),**phase.native_options())
        with parent.phase(RepositoryPhaseDemand('semantic_index')):
            semantic=build_codebase_semantic_manifest(index,policy_receipt_cid=policy['receipt_cid'],
                contracts=(IntegerOffsetContract('main.py','increment','n',1),IntegerOffsetContract('second.py','increment','n',2)))
        yield root,index,parent,CodebaseHead.from_dict(policy['head']),semantic,tmp_path
    connection.close()


def run(repository,tools=None,**kwargs):
    root,index,parent,head,semantic,tmp_path=repository
    result=module.execute_codebase_obligation_portfolio(index,root,expected_head=head,manifest_cid=semantic['manifest_cid'],
        paths=('main.py',),inputs=(-1,0,1),tools=native_tools() if tools is None else tools,parent=parent,**kwargs)
    (tmp_path/'last-result.json').write_text(json.dumps(result,indent=2))
    return result


def test_pure_typed_and_or_graph_keeps_proposals_and_explicit_bridge_dependencies():
    result=build_codebase_obligation_plans([bundle(),bundle(path='second.py')])
    assert len(result['alternatives'])==9 and not result['proof_claimed'] and not result['completion_claimed']
    graph=result['graph'];edges=graph['edges']
    assert any(e['source_node_id']=='unit0:bridge' and e['target_node_id']=='unit0:kernel' for e in edges)
    assert 'current-source' in {n['node_id'] for n in graph['nodes']}
    assert all(s['expected_receipts'] and s['completion_conditions'] for p in result['alternatives'] for s in p['steps'])


@pytest.mark.parametrize('values',[(),(0,0),(2,1),(False,),(0,65),tuple(range(17))])
def test_closed_finite_domain_refuses_unsupported_values(values):
    with pytest.raises(CodebaseFamilyError):CodebaseFamilyBundle(bundle().compiled,values)


@pytest.mark.parametrize('offset,inputs',[(2**31,(0,)),(1,(2**31-1,)),(-1,(-2**31+1,))])
def test_tlc_exact_machine_integer_range_is_explicit_not_an_unbounded_equivalence(offset,inputs):
    candidate=CodebaseFamilyBundle(bundle(offset=offset,contract=offset).compiled,inputs)
    with pytest.raises(CodebaseFamilyError,match='TLC integer'):candidate.to_dict()


def test_pure_single_flight_deduplicates_exact_obligations_but_not_changed_contracts():
    calls=[]
    def invoke(value,backend,bridge):calls.append((value.cid,backend,bridge));return value.cid
    with ThreadPoolExecutor(max_workers=2) as executor:
        flights=module._RunFlights(executor,{'scope':'pure concurrency control'},invoke)
        first=bundle();changed=bundle(contract=2)
        submitted=[flights.submit(first,'lean') for _ in range(8)]
        submitted.append(flights.submit(changed,'lean'))
        assert len({id(f) for f in submitted})==2
        assert [f.result() for f in submitted]==[first.cid]*8+[changed.cid]
    assert len(calls)==len(flights.entries)==2


def test_pure_selected_tool_identity_is_detached_and_changed_bytes_refuse(tmp_path):
    selected=tmp_path/'selected-tool';selected.write_text('explicit tool bytes, not executed')
    tools=seal_family_tools({k:str(selected) for k in (*BACKENDS,'java')})
    detached=validate_family_tools(tools,checkpoint=lambda:None)
    detached['tools']['lean']['artifacts'].append({'forged':'caller mutation'})
    assert not tools['tools']['lean']['artifacts']
    selected.write_text('replacement tool bytes, still not executed')
    with pytest.raises(CodebaseFamilyError,match='changed'):
        validate_family_tools(tools,checkpoint=lambda:None)


def test_actual_two_independent_units_six_native_families_and_required_bridges(repository):
    root,index,parent,head,semantic,tmp_path=repository
    result=module.execute_codebase_obligation_portfolio(index,root,expected_head=head,manifest_cid=semantic['manifest_cid'],
        paths=('main.py','second.py'),inputs=(-1,0,1),tools=native_tools(),parent=parent)
    (tmp_path/'native-two-unit-result.json').write_text(json.dumps(result,indent=2))
    assert result['status']=='proved',json.dumps([(u['mathematical_status'],{k:v['status'] for k,v in u['native_attempts'].items()},u['finite_attempt']['status'],u['bridge_attempt']['status']) for u in result['units']])
    assert result['final_source_validation'] and not result['source_runtime_semantics_verified']
    assert not result['task_completion_authority'] and result['inventory_coverage']['unmodeled_inventory_units']==1
    assert result['single_flight']['native_attempts']==14 and result['single_flight']['deduplicated']==8
    for unit in result['units']:
        assert all(r['status']=='proved' for r in unit['native_attempts'].values())
        assert all(r['status']=='proved' for r in unit['mathematical_selections'].values())
        for record in [*unit['native_attempts'].values(),unit['finite_attempt'],unit['bridge_attempt']]:
            assert record['native_observations'] and record['resource_binding']['child_lease_id']
            assert record['producer'] and all(o['workspace_cleaned'] for o in record['native_observations'])
        assert 'finite_restriction_bridge'==unit['bridge_attempt']['operation']


def test_actual_unavailable_kernels_do_not_promote_smt_and_tlc(repository):
    tools=native_tools()
    for backend in ('lean','rocq','isabelle'):tools['tools'][backend]['executable']=None
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
    tools['policy_cid']=cid_for_structured({k:v for k,v in tools.items() if k!='policy_cid'})
    result=run(repository,tools)
    assert result['status']=='unknown' and result['final_source_validation']
    unit=result['units'][0]
    assert all(unit['native_attempts'][b]['status']=='proved' for b in ('z3','cvc5'))
    assert unit['finite_attempt']['status']=='proved' and unit['bridge_attempt']['status']=='blocked'


def test_actual_optional_cancellation_preserves_required_lean_bridge_and_final_validation(repository):
    signal=threading.Event();signal.set()
    result=run(repository,optional_cancel_event=signal)
    assert result['status']=='proved' and result['final_source_validation']
    assert all(result['units'][0]['native_attempts'][b]['status']=='cancelled' for b in ('rocq','isabelle'))
    assert result['units'][0]['bridge_attempt']['status']=='proved'


def test_actual_contract_counterexample_is_kernel_checked_and_bridge_blocks(repository):
    root,index,parent,head,semantic,tmp_path=repository
    with parent.phase(RepositoryPhaseDemand('semantic_index')):
        wrong=build_codebase_semantic_manifest(index,policy_receipt_cid=index.artifacts.get(semantic['manifest_cid'])['policy_receipt_cid'],
            contracts=(IntegerOffsetContract('main.py','increment','n',2),))
    changed=(*repository[:4],wrong,tmp_path)
    result=run(changed)
    assert result['status']=='refuted' and result['final_source_validation']
    unit=result['units'][0]
    assert all(r['status']=='refuted' for r in unit['native_attempts'].values())
    assert unit['finite_attempt']['status']=='refuted' and unit['bridge_attempt']['status']=='blocked'


def test_injected_solver_disagreement_quarantines_with_real_other_family_receipts(repository,monkeypatch):
    real=module.execute_family
    def faulty(*args,**kwargs):
        value=real(*args,**kwargs)
        if kwargs['backend']=='cvc5':value['status']='refuted';value['fault_injection']='test-only altered solver verdict'
        return value
    monkeypatch.setattr(module,'execute_family',faulty)
    result=run(repository)
    assert result['status']=='quarantined' and result['units'][0]['bridge_attempt']['status']=='blocked'


def test_actual_source_change_invalidates_all_dependent_receipts(repository,monkeypatch):
    real=module.execute_family
    def change_after_bridge(*args,**kwargs):
        value=real(*args,**kwargs)
        if kwargs.get('bridge'):(repository[0]/'main.py').write_text('def increment(n: int) -> int:\n    return n + 8\n')
        return value
    monkeypatch.setattr(module,'execute_family',change_after_bridge)
    signal=threading.Event();signal.set()
    result=run(repository,optional_cancel_event=signal)
    assert result['status']=='invalidated' and not result['final_source_validation']
    assert result['units'][0]['dependent_status'].startswith('invalidated')
    assert result['units'][0]['native_attempts']['lean']['status']=='proved'  # historical exact model only


def test_unmodeled_selected_inventory_is_explicit_unsupported(repository):
    root,index,parent,head,semantic,_=repository
    result=module.execute_codebase_obligation_portfolio(index,root,expected_head=head,manifest_cid=semantic['manifest_cid'],
        paths=('README.txt',),inputs=(-1,0,1),tools=native_tools(),parent=parent)
    assert result['status']=='unsupported' and result['unsupported'][0]['status']=='unsupported_language'


def test_actual_parent_for_another_repository_refuses_before_phase_or_owner_reads(repository,monkeypatch):
    root,index,parent,head,semantic,_=repository
    other=CodebaseHead('other:repository',head.generation,head.manifest_cid,head.snapshot_cid,
        'rev:other:repository:snapshot:'+head.snapshot_cid,head.receipt_cid)
    def forbidden(*args,**kwargs):pytest.fail('wrong repository acquired a phase or read an owner')
    monkeypatch.setattr(parent,'phase',forbidden)
    monkeypatch.setattr(module,'load_codebase_semantic_manifest',forbidden)
    with pytest.raises(CodebaseFamilyError,match='repository'):
        module.execute_codebase_obligation_portfolio(index,root,expected_head=other,manifest_cid=semantic['manifest_cid'],
            paths=('main.py',),inputs=(-1,0,1),tools={},parent=parent)
