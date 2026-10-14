"""Source + synthetic metadata controls; never run builder or consume actual results."""
import ast
import copy
import hashlib
import json
import sys
from pathlib import Path
import unittest

F=Path(__file__).resolve().parent
SOURCE=F/'build_actor_refinement_release_spec_v01.py'
TREE=ast.parse(SOURCE.read_bytes())
NAMESPACE=dict(Path=Path,hashlib=hashlib,json=json,sys=sys,F=F,__file__=str(SOURCE))
assignments=[n for n in TREE.body if isinstance(n,ast.Assign)]
functions=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in {'require','private','read','expected_names'}]
exec(compile(ast.Module(body=assignments+functions,type_ignores=[]),str(SOURCE)+'#pure-controls','exec'),NAMESPACE)
MAIN=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='main')
ADD=next(n for n in MAIN.body if isinstance(n,ast.FunctionDef) and n.name=='add')


def scientific_checks():
    nodes=[]
    for n in MAIN.body:
        if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='require':
            text=ast.unparse(n)
            if "type(result_review['scientific_success'])" in text or "analysis['scientific_success']" in text:nodes.append(n)
    if len(nodes)!=2:raise AssertionError('Exact actual scientific-disposition requirements required')
    return nodes


class ReleaseBuilderControls(unittest.TestCase):
    def test_exact_62_result_geometry(self):
        names=NAMESPACE['expected_names']();self.assertEqual(len(names),62)
        self.assertIn('cell-checkpoint.json',names);self.assertIn('trained-frozen-head-retention.json',names)
        self.assertEqual(sum(n.endswith('-raw.json') for n in names),23)

    def test_source_prefix_and_current_recipe_versions(self):
        self.assertEqual(NAMESPACE['PREFIX'],'releases/20261014-actor-refinement-v1')
        self.assertEqual(NAMESPACE['REPO'],'Publicus/legal-ir-autoencoder')
        self.assertEqual(len(NAMESPACE['RECIPES']),len(set(NAMESPACE['RECIPES'])))
        for name in ('run_actor_refinement_v03.py','prepare_actor_refinement_v03.py','actor_refinement_bootstrap_smoke_controls_v03.py','freeze_actor_refinement_outputs_v03.py'):
            self.assertIn(name,NAMESPACE['RECIPES'])
        self.assertNotIn('reconcile_balanced_execution_root_identity_v01.py',NAMESPACE['RECIPES'])

    def test_no_payload_or_reference_metadata_read_before_freeze(self):
        ns=NAMESPACE.copy();calls=[];ns['pin']=lambda *a,**kw:calls.append(a)
        read=ns['read'];read.__globals__['FREEZE_PASSED']=False;old=read.__globals__.get('pin');read.__globals__['pin']=ns['pin']
        try:
            for p in (F/'actor-refinement-result-analysis-v01.json',F/'cell-checkpoint.json',F/'reference-packet.json'):
                with self.subTest(p=p),self.assertRaises(ValueError):read(p)
            self.assertEqual(calls,[])
        finally:
            if old is None:read.__globals__.pop('pin',None)
            else:read.__globals__['pin']=old

    def test_private_resource_bodies_denied(self):
        for p in (F/'private-runtime-snapshots/a.json',F/'private-root-identity-rebind-v01/a.json',F/'resources-start.json',F/'disk-reservations.json',F/'ipfs-datasets-resource-scheduler-1000.json'):
            with self.subTest(p=p):self.assertTrue(NAMESPACE['private'](p))
        self.assertFalse(NAMESPACE['private'](F/'owned-results-archive-actual-independent-review-v01.json'))

    def test_exact32MiB_payload_source_accepted_above_refused(self):
        ns=dict(NAMESPACE,files=[],destinations=set());amount=[32*1024*1024]
        ns['pin']=lambda p,expected=None:dict(path=str(p),bytes=amount[0],sha256='a'*64)
        exec(compile(ast.Module(body=[ADD],type_ignores=[]),str(SOURCE)+'#inner-add','exec'),ns)
        ns['add'](F/'opaque-checkpoint.json','cells/actor-refinement-ce/results/cell-checkpoint.json')
        self.assertEqual(len(ns['files']),1)
        amount[0]+=1
        with self.assertRaises(ValueError):ns['add'](F/'opaque2.json','cells/actor-refinement-ce/results/too-large.json')

    def test_duplicate_and_traversal_destinations_refuse(self):
        ns=dict(NAMESPACE,files=[],destinations=set(),pin=lambda p,expected=None:dict(path=str(p),bytes=7,sha256='a'*64))
        exec(compile(ast.Module(body=[ADD],type_ignores=[]),str(SOURCE)+'#inner-add','exec'),ns)
        ns['add'](F/'x.py','recipes/x.py')
        for suffix in ('recipes/x.py','../outside'):
            with self.subTest(suffix=suffix),self.assertRaises(ValueError):ns['add'](F/'x.py',suffix)

    def test_scientific_false_and_true_both_publish_without_promotion(self):
        nodes=scientific_checks()
        for success in (False,True):
            ns=dict(NAMESPACE,result_review=dict(scientific_success=success,default_promotion=False),
                analysis=dict(passed=True,findings=[],scientific_success=success,default_promotion=False),
                recount=dict(passed=True,findings=[],scientific_success=success,default_promotion=False))
            exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#science-controls','exec'),ns)

    def test_disposition_mismatch_or_promotion_refuses(self):
        nodes=scientific_checks();base=dict(result_review=dict(scientific_success=False,default_promotion=False),analysis=dict(passed=True,findings=[],scientific_success=False,default_promotion=False),recount=dict(passed=True,findings=[],scientific_success=False,default_promotion=False))
        for key,field,value in [('result_review','scientific_success',1),('analysis','scientific_success',True),('recount','scientific_success',True),('analysis','default_promotion',True),('result_review','default_promotion',True),('recount','passed',False)]:
            ns=dict(NAMESPACE,**copy.deepcopy(base));ns[key][field]=value
            with self.subTest(key=key,field=field),self.assertRaises(ValueError):exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#science-refusal','exec'),ns)

    def test_source_gate_precedes_any_freeze_metadata_read(self):
        text=ast.unparse(MAIN)
        self.assertLess(text.index("port = read(PORT_GATE, port_pin)"),text.index('freeze = read(FREEZE, freeze_pin)'))
        self.assertIn("port['builder'] == own",text);self.assertIn("port['helper'] == pin(F / 'archive_actor_refinement_hf_v01.py')",text)

    def test_manifest_is_copied_without_recursive_self_inventory(self):
        text=SOURCE.read_text()
        self.assertIn('manifest_self_excluded=True',text)
        self.assertIn('files=list(files)',text)
        self.assertLess(text.index("with MANIFEST.open('x')"),text.index("add(MANIFEST,'release-manifest.json',pin(MANIFEST))"))
        self.assertLess(text.index("add(MANIFEST,'release-manifest.json',pin(MANIFEST))"),text.index("with SPEC.open('x')"))

    def test_no_legacy_trainer_or_old_scientific_acceptance(self):
        text=SOURCE.read_text()
        self.assertNotIn('conditions-balanced',text);self.assertNotIn('relocation',text)
        self.assertIn("archive.algorithm_sources(plan,trainer)",text)
        self.assertIn("scientific_success=result_review['scientific_success']",text)
        self.assertIn('portable_reload_qualified=False',text)


if __name__=='__main__':unittest.main(verbosity=2)
