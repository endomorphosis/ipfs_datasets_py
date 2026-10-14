"""Bounded AST/fake controls only: never imports a real resource producer."""
import ast
import copy
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import types
import unittest

F = Path(__file__).resolve().parent
ADOPTION = F/'adopt_shared_scheduler_actor_ranking_v03.py'
WATCH = F/'owned_lease_watchdog_actor_ranking_v03.py'
BOOTSTRAP = F/'bootstrap_actor_context_ranking_resources_v02.py'
GUARDIAN = F/'run_scope_guardian_v04.py'
OUTPUT = F/'actor-context-ranking-current-resource-core-author-controls-v01.json'


def pin(path):
    b=path.read_bytes(); return dict(path=str(path),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())


def detached(path, functions, assignments=(), classes=()):
    nodes=[n for n in ast.parse(path.read_bytes()).body if
           isinstance(n,ast.FunctionDef) and n.name in functions or
           isinstance(n,ast.ClassDef) and n.name in classes or
           isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in assignments for t in n.targets)]
    scope=dict(__file__=str(path),Path=Path,deepcopy=copy.deepcopy,hashlib=hashlib,json=json,math=math,
               importlib=importlib,types=types,sys=sys)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<detached-core-fixtures>','exec'),scope)
    return scope


A=detached(ADOPTION,{'require','raw','digest','_validate_recovery_state','validated_config','exact_existing_client'},
           {'INTEGER_KEYS','OPTIONAL_INTEGER_KEYS','PERCENT_KEYS','OPTIONAL_PERCENT_KEYS','BOOLEAN_KEYS','PERSISTED_KEYS',
            'STATE_REQUIRED_KEYS','STATE_OPTIONAL_KEYS','EXPECTED_CONFIG','EXPECTED_CONFIG_SHA256','STATE_PATH'})
W=detached(WATCH,{'_require','_validate_recovery_state','owned_subtree_row_count'},classes={'LeaseWatchdogError'})


def state_fixture():
    return dict(schema_version='fixture-schema',config=copy.deepcopy(A['EXPECTED_CONFIG']),leases={'foreign':{}},
                waiters={'foreign-waiter':{}},metrics={'counter':7},next_sequence=8,proof_recovery={})


def fake_scheduler(state=None):
    state=state_fixture() if state is None else copy.deepcopy(state)
    class Config:
        def __init__(self,**values):
            self.state_path=values.pop('state_path');self.values=copy.deepcopy(values)
        def validate(self): return None
        def persisted_dict(self): return copy.deepcopy(self.values)
    class Error(ValueError): pass
    class Native:
        def __init__(self,config):
            self.config=config;self.super_flags=[]
            self._validate_state_configuration(copy.deepcopy(state),allow_reconfigure=True)
        def _validate_state_configuration(self,stored,*,allow_reconfigure=False):
            self.super_flags.append(allow_reconfigure)
        def acquire(self): return 'unchanged-native-admission-marker'
        def release(self): return 'unchanged-native-deferred-release-marker'
    return types.SimpleNamespace(RESOURCE_SCHEDULER_SCHEMA_VERSION='fixture-schema',
        ResourceSchedulerConfig=Config,ResourceConfigurationError=Error,GlobalResourceScheduler=Native,
        ResourceLane=(types.SimpleNamespace(value='validation'),))


def bootstrap_scope(modules=None):
    scope=detached(BOOTSTRAP,{'require','bootstrap'}, {'SOURCE','SOURCE_PINS','PACKAGES','MODULES'},
                   {'CheckedSourceLoader','ResourceOnlyFinder'})
    fake_sys=types.SimpleNamespace(modules={} if modules is None else dict(modules),meta_path=[],dont_write_bytecode=False)
    scope['sys']=fake_sys
    scope['checked_source']=lambda relative:(scope['SOURCE']/relative,b'SYNTHETIC_SOURCE_NOT_EXECUTED')
    def fake_import(name):
        module=types.ModuleType(name);module.__file__=str(scope['SOURCE']/scope['MODULES'][name]);fake_sys.modules[name]=module
        return module
    scope['importlib']=types.SimpleNamespace(abc=importlib.abc,machinery=importlib.machinery,
                                            util=importlib.util,import_module=fake_import)
    return scope


class Controls(unittest.TestCase):
    def test_complete24_validated_without_resource_calls(self):
        s=state_fixture();scheduler=fake_scheduler(s)
        cfg=A['validated_config'](scheduler,s,A['STATE_PATH'])
        self.assertEqual(cfg.persisted_dict(),A['EXPECTED_CONFIG']);self.assertEqual(len(cfg.persisted_dict()),24)

    def test_missing_unknown_or_changed_config_rejected(self):
        for change in ('missing','unknown','capacity','typed-bool'):
            s=state_fixture()
            if change=='missing':s['config'].pop('proof_recovery_enabled')
            elif change=='unknown':s['config']['SYNTHETIC_UNKNOWN']=0
            elif change=='capacity':s['config']['total_cpu_slots']=17
            else:s['config']['proof_recovery_enabled']=0
            with self.subTest(change=change),self.assertRaises(ValueError):
                A['validated_config'](fake_scheduler(s),s,A['STATE_PATH'])

    def test_wrong_global_endpoint_rejected(self):
        with self.assertRaises(ValueError):A['validated_config'](fake_scheduler(),state_fixture(),Path('/synthetic/other.json'))

    def test_constructor_true_forced_false_preserves_foreign_state(self):
        s=state_fixture();before=copy.deepcopy(s);scheduler=fake_scheduler(s)
        cfg=scheduler.ResourceSchedulerConfig(**copy.deepcopy(s['config']),state_path=A['STATE_PATH'])
        client=A['exact_existing_client'](scheduler,cfg)
        self.assertEqual(client.super_flags,[False]);self.assertEqual(s,before)
        self.assertIs(type(client).acquire,scheduler.GlobalResourceScheduler.acquire)
        self.assertIs(type(client).release,scheduler.GlobalResourceScheduler.release)

    def test_missing_state_cannot_initialize(self):
        scheduler=fake_scheduler();cfg=scheduler.ResourceSchedulerConfig(**copy.deepcopy(A['EXPECTED_CONFIG']),state_path=A['STATE_PATH'])
        client=A['exact_existing_client'](scheduler,cfg)
        with self.assertRaises(scheduler.ResourceConfigurationError):client._new_state()

    def test_reconfigure_true_never_accepts_changed_state(self):
        scheduler=fake_scheduler();cfg=scheduler.ResourceSchedulerConfig(**copy.deepcopy(A['EXPECTED_CONFIG']),state_path=A['STATE_PATH'])
        client=A['exact_existing_client'](scheduler,cfg);bad=state_fixture();bad['config']['total_cpu_slots']=17
        with self.assertRaises(scheduler.ResourceConfigurationError):client._validate_state_configuration(bad,allow_reconfigure=True)
        self.assertEqual(client.super_flags,[False])

    def test_disabled_recovery_only_absent_or_empty(self):
        for fn in (A['_validate_recovery_state'],W['_validate_recovery_state']):
            fn({},A['EXPECTED_CONFIG']);fn({'proof_recovery':{}},A['EXPECTED_CONFIG'])
            with self.assertRaises(ValueError):fn({'proof_recovery':{'phase':'settling'}},A['EXPECTED_CONFIG'])

    def test_native_recovery_closed_phase_counters_and_times(self):
        cfg=dict(A['EXPECTED_CONFIG'],proof_recovery_enabled=True)
        good=dict(phase='settling',healthy_samples=0,next_sample_at=1.,next_grant_at=0.,grants_remaining=4)
        for fn in (A['_validate_recovery_state'],W['_validate_recovery_state']):
            fn({'proof_recovery':good},cfg)
            fn({'proof_recovery':dict(good,phase='paced',healthy_samples=2)},cfg)
            for key,value in [('unknown',0),('healthy_samples',True),('grants_remaining',5),('next_sample_at',float('nan')),
                              ('next_grant_at',1),('phase','unknown')]:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    fn({'proof_recovery':dict(good,**{key:value})},cfg)

    def test_recovery_validator_exact_native_AST_mapping(self):
        tree=ast.parse((F/'resource-source-v01/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py').read_bytes())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GlobalResourceScheduler')
        fn=copy.deepcopy(next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_validate_recovery_state'))
        class Map(ast.NodeTransformer):
            def visit_Attribute(self,node):
                if isinstance(node.value,ast.Attribute) and isinstance(node.value.value,ast.Name) and node.value.value.id=='self' and node.value.attr=='config':
                    return ast.Subscript(value=ast.Name(id='config',ctx=ast.Load()),slice=ast.Constant(node.attr),ctx=node.ctx)
                return self.generic_visit(node)
            def visit_Name(self,node):
                if node.id=='SchedulerStateError':node.id='ValueError'
                return node
        fn=Map().visit(fn);fn.args=ast.parse('def x(state,config):pass').body[0].args;fn.returns=None
        for path in (ADOPTION,WATCH):
            other=next(n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==fn.name)
            self.assertEqual(ast.dump(fn,include_attributes=False),ast.dump(other,include_attributes=False))

    def test_deferred_release_requires_root_and_descendants_absent(self):
        count=W['owned_subtree_row_count']
        self.assertEqual(count({'foreign':{'parent_lease_id':None}},'own'),0)
        self.assertEqual(count({'own':{'parent_lease_id':None}},'own'),1)
        self.assertEqual(count({'child':{'parent_lease_id':'own'},'nested':{'parent_lease_id':'child'}},'own'),2)
        self.assertEqual(count({'own':{'parent_lease_id':'child'},'child':{'parent_lease_id':'own'}},'own'),2)
        with self.assertRaises(W['LeaseWatchdogError']):count({'foreign':{'parent_lease_id':[]}},'own')

    def test_bootstrap_fake_imports_only_three_resources(self):
        b=bootstrap_scope();package,scheduler,report=b['bootstrap']()
        self.assertEqual(len(b['sys'].modules),6);self.assertEqual(len(b['sys'].meta_path),1)
        self.assertFalse(report['package_initializers_executed']);self.assertFalse(report['router_deps_imported'])
        self.assertTrue(report['exact_source_bytes_compiled_directly'])
        self.assertTrue(all(b['sys'].modules[n].__resource_namespace_shell__ for n in b['PACKAGES']))

    def test_bootstrap_rejects_preloaded_namespace_or_numerical(self):
        for name in ('ipfs_datasets_py','ipfs_datasets_py.other','torch','numpy','huggingface_hub.utils'):
            with self.subTest(name=name),self.assertRaises(ValueError):bootstrap_scope({name:object()})['bootstrap']()

    def test_bootstrap_finder_denies_extra_and_numerical_modules(self):
        b=bootstrap_scope();finder=b['ResourceOnlyFinder']()
        for name in ('ipfs_datasets_py.router_deps','ipfs_datasets_py.unqualified','torch','numpy.random'):
            with self.subTest(name=name),self.assertRaises(ValueError):finder.find_spec(name)
        self.assertIsNone(finder.find_spec('json'))

    def test_loader_executes_only_checked_synthetic_bytes(self):
        b=bootstrap_scope();name=next(iter(b['MODULES']));relative=b['MODULES'][name];calls=[]
        def checked(rel):
            calls.append(rel);return b['SOURCE']/rel,b'SYNTHETIC_VALUE = 73\n'
        b['checked_source']=checked;module=types.ModuleType(name)
        b['CheckedSourceLoader'](name,relative).exec_module(module)
        self.assertEqual(module.SYNTHETIC_VALUE,73);self.assertEqual(calls,[relative,relative])

    def test_guardian_runtime_functions_exact_and_native6_pins(self):
        old={n.name:ast.dump(n,include_attributes=False) for n in ast.parse((F/'run_scope_guardian_v02.py').read_bytes()).body if isinstance(n,ast.FunctionDef)}
        new={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(GUARDIAN.read_bytes()).body if isinstance(n,ast.FunctionDef)}
        self.assertEqual(set(old),set(new));self.assertEqual({k for k in old if old[k]!=new[k]},{'load_module','closure_and_configuration'})
        manifest=json.loads((F/'resource-source-snapshot-v01.json').read_bytes())
        self.assertEqual(len(manifest['files']),6)
        for item in manifest['files'].values():
            self.assertEqual(pin(Path(item['snapshot']['path'])),item['snapshot'])
            self.assertEqual(pin(Path(item['origin']['path'])),item['origin'])

    def test_guardian_loader_has_no_bytecode_loader_route(self):
        fn=next(n for n in ast.parse(GUARDIAN.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='load_module')
        raw=ast.unparse(fn)
        self.assertIn('compile(raw',raw);self.assertNotIn('spec_from_file_location',raw);self.assertNotIn('exec_module',raw)
        boot=BOOTSTRAP.read_text();self.assertNotIn('spec_from_file_location',boot);self.assertNotIn('SourceFileLoader',boot)


if __name__=='__main__':
    sources={str(p):pin(p) for p in (ADOPTION,WATCH,BOOTSTRAP,GUARDIAN)}
    result=unittest.TestResult();unittest.defaultTestLoader.loadTestsFromTestCase(Controls).run(result)
    if not result.wasSuccessful():
        for _,error in result.failures+result.errors:print(error)
        raise SystemExit('Detached fake core controls failed')
    assert sources=={str(Path(p)):pin(Path(p)) for p in sources}
    assert not any(n.split('.')[0] in {'torch','numpy','transformers','sentence_transformers','huggingface_hub'} for n in sys.modules)
    value=dict(schema='actor-context-ranking-current-resource-core-author-controls/v1',passed=True,findings=[],
               controls_source=pin(Path(__file__).resolve()),artifacts=sources,tests_run=result.testsRun,
               failures=len(result.failures),errors=len(result.errors),independent_qualification=False,
               AST_and_synthetic_fake_namespace_only=True,actual_resource_imports=0,actual_resource_bootstrap_calls=0,
               actual_guardian_calls=0,private_body_reads=0,native_endpoint_reads=0,census_calls=0,
               resource_API_calls=0,claims_acquired=0,global_state_writes=0,model_calls=0)
    with OUTPUT.open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT),sort_keys=True))
