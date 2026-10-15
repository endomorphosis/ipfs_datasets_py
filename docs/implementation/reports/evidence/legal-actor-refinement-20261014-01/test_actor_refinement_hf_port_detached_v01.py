"""Finite pure/source-AST F15 archive-port controls; no helper main or evidence reads."""
import ast
import builtins
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'archive_actor_refinement_hf_v01.py'
PREFIX='releases/20261014-actor-refinement-v1'
PRIOR='0228887c8e33cb23e9679889a9496f87140021e6'
ATTENTION='ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_temporal_attention.py'


def denied(name,*args,**kwargs):raise AssertionError('No real import in detached port controls: '+name)


def namespace():
    names={'require','private','brief','destination','identities','qualify_hf_baseline','algorithm_sources','chunks','byte_identity','approved'}
    tree=ast.parse(SOURCE.read_bytes());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if len(nodes)!=len(names) or {n.name for n in nodes}!=names:raise AssertionError('Exact pure helper set')
    if any(n.decorator_list or any(isinstance(c,(ast.Import,ast.ImportFrom)) for c in ast.walk(n)) for n in nodes):raise AssertionError('Detached imports/decorators refused')
    ns=dict(Path=Path,hashlib=hashlib,F=ROOT,REPO='Publicus/legal-ir-autoencoder',PREFIX=PREFIX,MAX_BYTES=200000000,MAX_FILE_BYTES=32*1024*1024,
        CHUNK_TARGET_BYTES=16000000,CHUNK_MAX_FILES=48,MAX_REMOTE_FILES=12000,PRIOR_REVISION=PRIOR,PRIOR_FILES=5448,
        OWNER_COUNT=39,ALGORITHM_SOURCE_COUNT=40,SUPPLEMENT_RELATIVE=ATTENTION,SUPPLEMENT_BYTES=56776,
        SUPPLEMENT_SHA256='fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731')
    ns['__builtins__']=dict(vars(builtins),__import__=denied)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#pure-controls','exec'),ns)
    return ns


def descriptor(size=1):return dict(bytes=size,sha256='a'*64)


def remote_identity():return dict(size=1,blob_id='a'*40,lfs=None)


def baseline_fixture():
    prior={'.gitattributes':remote_identity(),**{'historical/'+str(i):remote_identity() for i in range(5447)}}
    return dict(repo='Publicus/legal-ir-autoencoder',revision='3'*40,files={**copy.deepcopy(prior),'concurrent-new.json':remote_identity()},
        prior_release_revision=PRIOR,prior_release_files=prior)


def algorithm_fixture():
    owners={'module'+str(i):dict(path=str(ROOT/'datasets/ipfs_datasets_py'/('owner'+str(i)+'.py')),**descriptor()) for i in range(39)}
    supplemental=dict(path=str(ROOT/'datasets'/ATTENTION),bytes=56776,sha256='fb8670887177ac56379fa76dc9efe310b3a5d598f09c21a3d47e5bf960bc1731')
    plan=dict(schema='actor-refinement-cell-plan/v1',cell='actor-refinement-ce',attempt_name='actor-refinement-20261014-actor-refinement-ce-01',
        package_root=str(ROOT/'datasets'),source_owner_pins=owners,artifacts={v['path']:{k:v[k] for k in ('bytes','sha256')} for v in [*owners.values(),supplemental]})
    review=dict(schema='actor-refinement-trainer-source-independent-review/v1',passed=True,findings=[],source_owner_pins=copy.deepcopy(owners),supplemental_source_pins={ATTENTION:supplemental})
    return plan,review


class Controls(unittest.TestCase):
    def setUp(self):self.n=namespace()
    def test_current_inventory_and5448_anchor_both_preserved(self):
        value=baseline_fixture();self.assertIs(self.n['qualify_hf_baseline'](value),value)
        self.assertEqual(len(value['files']),5449)
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
    def test_exact40_sources_include_supplement(self):
        plan,review=algorithm_fixture();value=self.n['algorithm_sources'](plan,review)
        self.assertEqual(len(value),40);self.assertIn(PREFIX+'/source/'+ATTENTION,value)
    def test_source_closure_missing_unadmitted_duplicate_or_wrong_recipe_refused(self):
        for mode in ('missing','unadmitted','duplicate','package','gate','attention'):
            plan,review=algorithm_fixture()
            if mode=='missing':plan['source_owner_pins'].pop('module0')
            elif mode=='unadmitted':plan['artifacts'].pop(plan['source_owner_pins']['module0']['path'])
            elif mode=='duplicate':
                plan['source_owner_pins']['module1']=plan['source_owner_pins']['module0'];review['source_owner_pins']=copy.deepcopy(plan['source_owner_pins'])
            elif mode=='package':plan['package_root']='/old/datasets'
            elif mode=='gate':review['schema']='conditions-balanced-trainer-relocation-source-independent-review/v1'
            else:review['supplemental_source_pins'][ATTENTION]['sha256']='f'*64
            with self.assertRaises(ValueError):self.n['algorithm_sources'](plan,review)
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
        self.assertIn('actor-refinement-Hub-helper-port-source-independent-review/v1',prefix)
    def test_actualF15_tests_V03_recipes_and_trainer_gate_source_interfaces(self):
        text=SOURCE.read_text()
        for value in ('test_legal_span_actor_refinement_contracts.py','run_actor_refinement_v03.py','prepare_actor_refinement_v03.py',
            'actor_refinement_bootstrap_smoke_controls_v03.py','trainer-source-independent-review-v01.json','trainer_source_qualification',
            'actor-refinement-result-independent-review-v01.json'):
            self.assertIn(value,text)


if __name__=='__main__':unittest.main()
