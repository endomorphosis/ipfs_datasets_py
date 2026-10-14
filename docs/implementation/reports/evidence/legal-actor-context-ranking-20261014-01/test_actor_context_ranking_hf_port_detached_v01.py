"""Finite pure/source-AST F16 archive-port controls; no helper main or evidence reads."""
import ast
import builtins
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'archive_actor_context_ranking_hf_v01.py'
PREFIX='releases/20261014-actor-context-ranking-v1'
PRIOR='1622817fd804ff5333fce7dc8d04433e4acef2e4'
ATTENTION='ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py'


def denied(name,*args,**kwargs):raise AssertionError('No real import in detached port controls: '+name)


def namespace():
    names={'require','private','brief','destination','identities','qualify_hf_baseline','algorithm_sources','chunks','byte_identity','approved'}
    tree=ast.parse(SOURCE.read_bytes());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if len(nodes)!=len(names) or {n.name for n in nodes}!=names:raise AssertionError('Exact pure helper set')
    if any(n.decorator_list or any(isinstance(c,(ast.Import,ast.ImportFrom)) for c in ast.walk(n)) for n in nodes):raise AssertionError('Detached imports/decorators refused')
    ns=dict(Path=Path,hashlib=hashlib,F=ROOT,REPO='Publicus/legal-ir-autoencoder',PREFIX=PREFIX,MAX_BYTES=200000000,MAX_FILE_BYTES=32*1024*1024,
        CHUNK_TARGET_BYTES=16000000,CHUNK_MAX_FILES=48,MAX_REMOTE_FILES=12000,PRIOR_REVISION=PRIOR,PRIOR_FILES=5646,
        OWNER_COUNT=40,ALGORITHM_SOURCE_COUNT=41,SUPPLEMENT_RELATIVE=ATTENTION,SUPPLEMENT_BYTES=56776,
        SUPPLEMENT_SHA256='fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731')
    ns['__builtins__']=dict(vars(builtins),__import__=denied)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#pure-controls','exec'),ns)
    return ns


def descriptor(size=1):return dict(bytes=size,sha256='a'*64)


def remote_identity():return dict(size=1,blob_id='a'*40,lfs=None)


def baseline_fixture():
    prior={'.gitattributes':remote_identity(),**{'historical/'+str(i):remote_identity() for i in range(5645)}}
    return dict(repo='Publicus/legal-ir-autoencoder',revision='3'*40,files={**copy.deepcopy(prior),'concurrent-new.json':remote_identity()},
        prior_release_revision=PRIOR,prior_release_files=prior)


def algorithm_fixture():
    prefix='ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    names=[prefix+'synthetic_owner'+str(i) for i in range(39)]+[prefix+'legal_span_actor_context_ranking']
    owners={name:dict(path=str(ROOT/'datasets'/(name.replace('.','/')+'.py')),**descriptor()) for name in names}
    supplemental=dict(path=str(ROOT/'datasets'/ATTENTION),bytes=56776,sha256='fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731')
    test=dict(path=str(ROOT/'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_context_ranking_contracts.py'),**descriptor())
    plan=dict(schema='actor-context-ranking-cell-plan/v1',cell='actor-context-ranking-hinge',attempt_name='actor-context-ranking-20261014-actor-context-ranking-hinge-01',
        package_root=str(ROOT/'datasets'),source_owner_pins=owners,artifacts={v['path']:{k:v[k] for k in ('bytes','sha256')} for v in [*owners.values(),supplemental,test]})
    model=owners[prefix+'legal_span_actor_context_ranking']
    review=dict(schema='actor-context-ranking-trainer-source-independent-review/v1',passed=True,findings=[],source=copy.deepcopy(model),tests=test,
        artifacts={v['path']:copy.deepcopy(v) for v in (model,test)})
    return plan,review


class Controls(unittest.TestCase):
    def setUp(self):self.n=namespace()
    def test_current_inventory_and5646_anchor_both_preserved(self):
        value=baseline_fixture();self.assertIs(self.n['qualify_hf_baseline'](value),value)
        self.assertEqual(len(value['files']),5647)
    def test_anchor_missing_changed_prefix_or_bad_baseline_refused(self):
        mutations=(lambda v:v['files'].pop('historical/0'),lambda v:v['files']['historical/0'].update(blob_id='b'*40),
            lambda v:v['prior_release_files'].pop('historical/0'),lambda v:v.update(prior_release_revision='4'*40),
            lambda v:v['files'].update({PREFIX+'/existing':remote_identity()}),lambda v:v.update(revision='z'*40),lambda v:v.update(extra=True))
        for mutate in mutations:
            value=baseline_fixture();mutate(value)
            with self.assertRaises(ValueError):self.n['qualify_hf_baseline'](value)
    def test_malformed_saved_remote_LFS_identity_refused(self):
        value=baseline_fixture();value['files']['concurrent-new.json']['lfs']=dict(size=True,sha256='a'*64,pointer_size=130)
        with self.assertRaises(ValueError):self.n['qualify_hf_baseline'](value)
    def test_sdk_typed_hex_Git_and_LFS_identity(self):
        item=SimpleNamespace(rfilename='model',size=2,blob_id='a'*40,lfs=SimpleNamespace(size=2,sha256='b'*64,pointer_size=130))
        value=self.n['identities'](SimpleNamespace(sha='1'*40,siblings=[item]))
        self.assertEqual(value['model']['lfs']['sha256'],'b'*64)
    def test_sdk_identity_malformed_cases(self):
        for mode in ('revision','blob','size','LFSsize','LFSsha','LFSpointer','duplicate'):
            item=SimpleNamespace(rfilename='model',size=2,blob_id='a'*40,lfs=SimpleNamespace(size=2,sha256='b'*64,pointer_size=130))
            info=SimpleNamespace(sha='1'*40,siblings=[item])
            if mode=='revision':info.sha='z'*40
            elif mode=='blob':item.blob_id='z'*40
            elif mode=='size':item.size=True
            elif mode=='LFSsize':item.lfs.size=3
            elif mode=='LFSsha':item.lfs.sha256='z'*64
            elif mode=='LFSpointer':item.lfs.pointer_size=0
            else:info.siblings.append(item)
            with self.assertRaises(ValueError):self.n['identities'](info)
    def test_exact41_sources_include_supplement_without_legacy_trainer_fields(self):
        plan,review=algorithm_fixture();value=self.n['algorithm_sources'](plan,review)
        self.assertEqual(len(value),41);self.assertIn(PREFIX+'/source/'+ATTENTION,value)
        self.assertNotIn('source_owner_pins',review);self.assertNotIn('supplemental_source_pins',review)
    def test_actual_frozen_plan_and_trainer_metadata_shape(self):
        import json
        plan=json.loads((ROOT/'actor-context-ranking-hinge-plan-v01.json').read_bytes())
        review=json.loads((ROOT/'trainer-source-independent-review-v01.json').read_bytes())
        self.assertEqual(len(self.n['algorithm_sources'](plan,review)),41)
    def test_supplement_requires_exact_frozen_plan_admission(self):
        key=str(ROOT/'datasets'/ATTENTION)
        for mode in ('missing','relative','wrong_hash','wrong_bytes'):
            plan,review=algorithm_fixture();mapping=plan['artifacts']
            if mode=='missing':mapping.pop(key)
            elif mode=='relative':mapping[ATTENTION]=mapping.pop(key)
            elif mode=='wrong_hash':mapping[key]['sha256']='f'*64
            else:mapping[key]['bytes']+=1
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.n['algorithm_sources'](plan,review)
    def test_source_closure_missing_unadmitted_duplicate_or_wrong_trainer_refused(self):
        key='ipfs_datasets_py.optimizers.logic_theorem_optimizer.synthetic_owner0'
        for mode in ('missing','unadmitted','duplicate','package','gate','model','test','trainer_artifact','module_path'):
            plan,review=algorithm_fixture()
            if mode=='missing':plan['source_owner_pins'].pop(key)
            elif mode=='unadmitted':plan['artifacts'].pop(plan['source_owner_pins'][key]['path'])
            elif mode=='duplicate':plan['source_owner_pins'][key]=copy.deepcopy(plan['source_owner_pins']['ipfs_datasets_py.optimizers.logic_theorem_optimizer.synthetic_owner1'])
            elif mode=='package':plan['package_root']='/old/datasets'
            elif mode=='gate':review['schema']='actor-refinement-trainer-source-independent-review/v1'
            elif mode=='model':review['source']['sha256']='f'*64
            elif mode=='test':review['tests']['path']=str(ROOT/'wrong.py')
            elif mode=='trainer_artifact':review['artifacts'][review['source']['path']]['sha256']='f'*64
            else:plan['source_owner_pins']['ipfs_datasets_py.wrong']=plan['source_owner_pins'].pop(key)
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.n['algorithm_sources'](plan,review)
    def test_private_diagnostics_and_global_bodies_excluded(self):
        for path in ('private-resource-diagnostics/guardian-check-v01/stderr.bin','private-runtime-snapshots/opening-v01/ledger.json',
                'private-root-identity-rebind-v01/ledger-before.json','resources-start.json','resources-final.json','disk-reservations.json'):
            self.assertTrue(self.n['private'](ROOT/path))
        self.assertFalse(self.n['private'](ROOT/'guardian-check-diagnostic-v01.json'))
    def test_required_missing_public_source_does_not_silently_skip(self):
        def missing(path):raise FileNotFoundError('synthetic absent required source')
        self.n['pin']=missing
        with self.assertRaises(FileNotFoundError):self.n['approved'](dict(artifacts={'/synthetic/required.py':descriptor()}))
    def test_no_historical_path_filter(self):
        tree=ast.parse(SOURCE.read_bytes());self.assertFalse(any(isinstance(n,ast.FunctionDef) and n.name=='historical_result' for n in tree.body))
    def test_chunks48_files_and16M_boundary(self):
        entries={str(i).zfill(2):descriptor(1) for i in range(49)};groups=self.n['chunks'](entries)
        self.assertEqual(list(map(len,groups)),[48,1])
        self.assertEqual(self.n['chunks']({'a':descriptor(8000000),'b':descriptor(8000000),'c':descriptor(1)}),[['a','b'],['c']])
    def test_large32MiB_file_is_explicit_singleton(self):
        entries={'a':descriptor(1),'b':descriptor(32*1024*1024),'c':descriptor(1)}
        self.assertEqual(self.n['chunks'](entries),[['a'],['b'],['c']])
        with self.assertRaises(ValueError):self.n['chunks']({'large':descriptor(32*1024*1024+1)})
    def test_chunk_both_budgets_or_single_large_file_hold(self):
        entries={str(i).zfill(3):descriptor((i%7)*1000000+1) for i in range(73)};groups=self.n['chunks'](entries)
        self.assertEqual(sum(groups,[]),sorted(entries))
        self.assertTrue(all(len(g)<=48 and (sum(entries[n]['bytes'] for n in g)<=16000000 or len(g)==1) for g in groups))
    def test_new_prefix_destination_rejects_traversal_and_noncanonical_names(self):
        self.assertEqual(self.n['destination'](PREFIX+'/source/module.py'),PREFIX+'/source/module.py')
        for name in ('/absolute',PREFIX+'/../escape',PREFIX+'//double',PREFIX+'/bad\\name',PREFIX+'/bad\nname','releases/other/file'):
            with self.assertRaises(ValueError):self.n['destination'](name)
    def test_Git_and_LFS_content_identity(self):
        raw=b'synthetic opaque checkpoint bytes';git=dict(size=len(raw),blob_id=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),lfs=None)
        lfs=dict(size=len(raw),blob_id='a'*40,lfs=dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),pointer_size=130))
        for identity in (git,lfs):
            self.assertTrue(self.n['byte_identity'](identity,raw));self.assertFalse(self.n['byte_identity'](identity,raw+b'x'))
    def test_baseline_gate_precedes_real_SDK_import(self):
        tree=ast.parse(SOURCE.read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='baseline')
        first_import=next(i for i,n in enumerate(fn.body) if isinstance(n,(ast.Import,ast.ImportFrom)))
        prefix=ast.unparse(ast.Module(body=fn.body[:first_import],type_ignores=[]))
        self.assertIn('hf-helper-port-source-independent-review-v01.json',prefix)
        self.assertIn("review['helper'] == own",prefix)
        self.assertIn('actor-context-ranking-Hub-helper-port-source-independent-review/v1',prefix)
    def test_actualF16_tests_V03_recipes_and_trainer_gate_source_interfaces(self):
        text=SOURCE.read_text()
        for value in ('test_legal_span_actor_context_ranking_contracts.py','run_actor_context_ranking_v04.py','prepare_actor_context_ranking_v04.py',
            'actor_context_ranking_bootstrap_smoke_controls_v04.py','trainer-source-independent-review-v01.json','trainer_source_qualification',
            'actor-context-ranking-result-independent-review-v01.json'):
            self.assertIn(value,text)


if __name__=='__main__':unittest.main(verbosity=2)
