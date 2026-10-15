"""Detached source-loader guard controls; no production module is executed."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import types
import unittest

F=Path(__file__).resolve().parent
RUNNER=F/'run_actor_context_ranking_v04.py'
PREP=F/'prepare_actor_context_ranking_v04.py'
SMOKE=F/'actor_context_ranking_bootstrap_smoke_controls_v04.py'
OUTPUT=F/'actor-context-ranking-current-recipe-independent-controls-v02.json'


def pin(path):
    b=path.read_bytes();return dict(path=str(path),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())


def functions(path):
    return {n.name:n for n in ast.parse(path.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}


def checked_block(path, function=None):
    tree=ast.parse(path.read_bytes())
    body=tree.body if function is None else next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function).body
    start=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_checked_path' for t in n.targets))
    end=next(i for i in range(start,len(body)) if isinstance(body[i],ast.Expr) and isinstance(body[i].value,ast.Call)
             and isinstance(body[i].value.func,ast.Name) and body[i].value.func.id=='exec')
    return ast.Module(body=copy.deepcopy(body[start:end+1]),type_ignores=[])


class StoppedBeforeExecution(Exception): pass


class FixturePath:
    def __init__(self,raw):self.raw=raw
    def read_bytes(self):return self.raw
    def __truediv__(self,_):return self
    def __str__(self):return '/synthetic/authenticated-helper.py'


def stop_module(*args):raise StoppedBeforeExecution()


def run_block(path,function,raw):
    fixture=FixturePath(raw)
    scope=dict(RUNNER=fixture,F=fixture,protocol_path=fixture,hashlib=hashlib,
               types=types.SimpleNamespace(ModuleType=stop_module))
    exec(compile(checked_block(path,function),'<detached-raw-guard>','exec'),scope)


class Normalize(ast.NodeTransformer):
    def visit_Constant(self,node):
        if type(node.value) is str:
            for old,new in [('run_actor_context_ranking_v03.py','run_actor_context_ranking_v04.py'),
                ('actor-context-ranking-bootstrap-smoke-controls-v03.json','actor-context-ranking-bootstrap-smoke-controls-v04.json'),
                ('run_scope_guardian_v02.py','run_scope_guardian_v04.py'),
                ('actor_context_ranking_resource_protocol_v01.py','actor_context_ranking_resource_protocol_v03.py'),
                ('runner-preparer-source-independent-review-v01.json','runner-preparer-source-independent-review-v02.json'),
                ('actor_context_ranking_bootstrap_smoke_controls_v03.py','actor_context_ranking_bootstrap_smoke_controls_v04.py')]:
                node.value=node.value.replace(old,new)
        return node


class Controls(unittest.TestCase):
    def test_unchanged_smoke_guard_kernels(self):
        old=functions(F/'actor_context_ranking_bootstrap_smoke_controls_v03.py');new=functions(SMOKE)
        for name in ('require','pin','NoNumerical','audit','mandatory'):
            self.assertEqual(ast.dump(old[name],include_attributes=False),ast.dump(new[name],include_attributes=False))

    def test_exact_guard_passes_without_executing_helper(self):
        for path,function,raw in [(SMOKE,'main',RUNNER.read_bytes()),(PREP,None,RUNNER.read_bytes()),
                                  (RUNNER,'qualify_resource_baseline',(F/'actor_context_ranking_resource_protocol_v03.py').read_bytes())]:
            with self.subTest(path=path.name),self.assertRaises(StoppedBeforeExecution):run_block(path,function,raw)

    def test_wrong_size_rejected_before_module_creation(self):
        for path,function in [(SMOKE,'main'),(PREP,None),(RUNNER,'qualify_resource_baseline')]:
            with self.subTest(path=path.name),self.assertRaises(ValueError):run_block(path,function,b'not the authenticated source')

    def test_same_size_wrong_hash_rejected_before_module_creation(self):
        for path,function,raw in [(SMOKE,'main',RUNNER.read_bytes()),(PREP,None,RUNNER.read_bytes()),
                                  (RUNNER,'qualify_resource_baseline',(F/'actor_context_ranking_resource_protocol_v03.py').read_bytes())]:
            wrong=bytes([raw[0]^1])+raw[1:]
            with self.subTest(path=path.name),self.assertRaises(ValueError):run_block(path,function,wrong)

    def test_smoke_guards_installed_before_runner_buffer_exec(self):
        fn=functions(SMOKE)['main']
        installs=[n.lineno for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                  and ast.unparse(n) in ('sys.meta_path.insert(0, NoNumerical())','sys.addaudithook(audit)')]
        execs=[n.lineno for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='exec']
        self.assertTrue(installs and execs and max(installs)<min(execs))

    def test_scientific_runner_functions_exact_after_path_labels(self):
        old=functions(F/'run_actor_context_ranking_v03.py');new=functions(RUNNER)
        self.assertEqual(set(old),set(new))
        changed=[]
        for name in old:
            normalized=Normalize().visit(copy.deepcopy(old[name]))
            if ast.dump(normalized,include_attributes=False)!=ast.dump(new[name],include_attributes=False):changed.append(name)
        self.assertEqual(sorted(changed),['legacy_runner','qualify_resource_baseline'])

    def test_preparer_science_exact_after_producer_labels(self):
        old=Normalize().visit(copy.deepcopy(functions(F/'prepare_actor_context_ranking_v03.py')['prepare']))
        self.assertEqual(ast.dump(old,include_attributes=False),ast.dump(functions(PREP)['prepare'],include_attributes=False))

    def test_direct_metadata_loaders_no_SourceFileLoader(self):
        for path,fn in [(RUNNER,'legacy_runner'),(RUNNER,'qualify_resource_baseline')]:
            raw=ast.unparse(functions(path)[fn])
            self.assertIn('compile(',raw);self.assertNotIn('spec_from_file_location',raw)
        self.assertNotIn('spec_from_file_location',PREP.read_text())
        self.assertNotIn('spec_from_file_location',SMOKE.read_text())


if __name__=='__main__':
    before={str(p):pin(p) for p in (RUNNER,PREP,SMOKE)}
    result=unittest.TestResult();unittest.defaultTestLoader.loadTestsFromTestCase(Controls).run(result)
    if not result.wasSuccessful():
        for _,error in result.failures+result.errors:print(error)
        raise SystemExit('Detached current recipe guards failed')
    assert before=={p:pin(Path(p)) for p in before}
    receipt=dict(schema='actor-context-ranking-current-recipe-independent-controls/v1',passed=True,findings=[],
                 controls_source=pin(Path(__file__).resolve()),artifacts=before,tests_run=result.testsRun,
                 failures=len(result.failures),errors=len(result.errors),source_AST_and_fake_loader_only=True,
                 guard_positive_fixture_stops_before_any_production_code_execution=True,
                 inherited31_bootstrap_guards_and17_scientific_harness_cases_not_rerun=True,
                 production_module_imports=0,production_main_calls=0,private_body_reads=0,
                 resource_calls=0,checkpoint_JSON_parses=0,model_calls=0,numerical_imports=0)
    with OUTPUT.open('x') as stream:json.dump(receipt,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT),sort_keys=True))
