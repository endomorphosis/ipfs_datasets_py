"""Detached F16 partial-observer controls; no observer main/SDK/private/model reads."""
import ast
import builtins
import copy
import hashlib
import json
from pathlib import Path
import unittest

F=Path(__file__).resolve().parent
SOURCE=F/'observe_actor_context_ranking_hf_partial_v01.py'
TREE=ast.parse(SOURCE.read_bytes())
NAMES={'require','qualify_local','payload_matches','compare_snapshot','classify_attributes'}

def namespace():
    nodes=[n for n in TREE.body if isinstance(n,ast.Assign) or isinstance(n,ast.FunctionDef) and n.name in NAMES]
    def safe_import(name,*a,**kw):
        if name!='collections':raise AssertionError('Only stdlib collections permitted in detached source helpers')
        return builtins.__import__(name,*a,**kw)
    ns=dict(Path=Path,hashlib=hashlib,__file__=str(SOURCE),__builtins__={**vars(builtins),'__import__':safe_import})
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'#detached','exec'),ns)
    return ns


def fixture(ns):
    groups=[];index=0
    for count in [18,1,1,15,18,37,48,48,15]:
        groups.append([ns['PREFIX']+'/synthetic/%03d'%i for i in range(index,index+count)]);index+=count
    groups[2]=[ns['CHECKPOINT']]
    entries={n:dict(path='/synthetic/'+str(i),bytes=1,sha256='a'*64) for i,n in enumerate(n for g in groups for n in g)}
    entries[ns['CHECKPOINT']].update(bytes=ns['CHECKPOINT_BYTES'],sha256=ns['CHECKPOINT_SHA256'])
    before=dict(revision=ns['BASELINE'],files={'old/'+str(i):dict(size=1,blob_id='a'*40,lfs=None) for i in range(5646)})
    baseline=dict(path='/synthetic/baseline.json',bytes=1,sha256='a'*64)
    receipt=dict(schema='actor-context-ranking-Hub-preparation/v1',repository=ns['REPO'],release_prefix=ns['PREFIX'],expected_parent_revision=ns['BASELINE'],
        payload_files=201,payload_bytes=81437344,entries=entries,algorithm_source_count=41,algorithm_sources={str(i):{} for i in range(41)},default_promotion=False,additions_only=True,baseline=baseline)
    spec=dict(schema='actor-context-ranking-Hub-release-spec/v1',repository=ns['REPO'],release_prefix=ns['PREFIX'],baseline=baseline,
        files=[dict(source=d,destination=n) for n,d in entries.items()])
    created=[dict(parent_revision=p,revision=r,names=groups[i]) for i,(p,r) in enumerate(((ns['BASELINE'],ns['FIRST']),(ns['FIRST'],ns['SECOND']),(ns['SECOND'],ns['PARTIAL'])))]
    verified=[dict(parent_revision=c['parent_revision'],revision=c['revision'],new_files=len(c['names']),old_identities_exact=True,new_byte_identities_exact=True) for c in created[:2]]
    return before,receipt,spec,created,verified,groups


class Controls(unittest.TestCase):
    def setUp(self):self.n=namespace()
    def test_exact_original_geometry_and20_created_files(self):
        self.assertEqual(len(self.n['qualify_local'](*fixture(self.n))),20)
    def test_actual_public_preparation_and_chunk_metadata(self):
        read=lambda n:json.loads((F/n).read_bytes())
        helper=ast.parse((F/'archive_actor_context_ranking_hf_v01.py').read_bytes())
        node=next(n for n in helper.body if isinstance(n,ast.FunctionDef) and n.name=='chunks')
        ns=dict(require=self.n['require'],brief=lambda d:{k:d[k] for k in ('bytes','sha256')},MAX_FILE_BYTES=32*1024*1024,CHUNK_TARGET_BYTES=16000000,CHUNK_MAX_FILES=48)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'#retained-chunks','exec'),ns)
        receipt=read('hf-preparation-receipt-v01.json')
        out=self.n['qualify_local'](read('hf-before-file-identities-v01.json'),receipt,read('hf-release-spec-v01.json'),
            [read('hf-chunk-%02d-created-v01.json'%i) for i in (1,2,3)],
            [read('hf-chunk-%02d-verified-v01.json'%i) for i in (1,2)],ns['chunks'](receipt['entries']))
        self.assertEqual(len(out),20)
    def test_wrong_geometry_payload_lineage_or_old_verified_receipt_refused(self):
        for mode in ('count','bytes','algorithm','first_parent','first_revision','second_verified','checkpoint','groups','spec','baseline','promotion'):
            args=list(fixture(self.n));b,r,s,c,v,g=args
            if mode=='count':r['payload_files']=200
            elif mode=='bytes':r['payload_bytes']+=1
            elif mode=='algorithm':r['algorithm_source_count']=40
            elif mode=='first_parent':c[0]['parent_revision']='0'*40
            elif mode=='first_revision':c[0]['revision']='0'*40
            elif mode=='second_verified':v[1]['old_identities_exact']=False
            elif mode=='checkpoint':r['entries'][self.n['CHECKPOINT']]['sha256']='0'*64
            elif mode=='groups':g[2]=g[1]
            elif mode=='spec':s['files'].pop()
            elif mode=='baseline':b['revision']='0'*40
            else:r['default_promotion']=True
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.n['qualify_local'](*args)
    def test_Git_byte_identity_requires_opaque_blob_digest(self):
        self.assertTrue(self.n['payload_matches'](dict(size=3,blob_id='a'*40,lfs=None),dict(bytes=3,sha256='b'*64),'a'*40))
        self.assertFalse(self.n['payload_matches'](dict(size=3,blob_id='a'*40,lfs=None),dict(bytes=3,sha256='b'*64),None))
    def test_checkpoint_LFS_identity_can_be_verified_without_opening_checkpoint(self):
        d=dict(bytes=self.n['CHECKPOINT_BYTES'],sha256=self.n['CHECKPOINT_SHA256'])
        identity=dict(size=d['bytes'],blob_id='a'*40,lfs=dict(size=d['bytes'],sha256=d['sha256'],pointer_size=135))
        self.assertTrue(self.n['payload_matches'](identity,d,None));identity['lfs']['sha256']='f'*64
        self.assertFalse(self.n['payload_matches'](identity,d,None))
    def test_only_attributes_difference_is_classified_without_passing_original_invariant(self):
        original={'.gitattributes':dict(size=1,blob_id='a'*40,lfs=None),'historical':dict(size=1,blob_id='b'*40,lfs=None)}
        current=copy.deepcopy(original);current['.gitattributes']['size']=2
        v=self.n['compare_snapshot'](original,current,[],{}, {})
        self.assertFalse(v['all_original_identities_exact']);self.assertTrue(v['all_original_non_attributes_identities_exact'])
        self.assertEqual(set(v['old_identity_differences']),{'.gitattributes'})
    def test_foreign_old_change_missing_and_unexpected_paths_are_visible(self):
        original={'old':dict(size=1,blob_id='a'*40,lfs=None)}
        for current in ({'old':dict(size=2,blob_id='a'*40,lfs=None)},{},{'old':original['old'],'foreign':original['old']}):
            v=self.n['compare_snapshot'](original,current,[],{}, {})
            self.assertTrue(v['old_identity_differences'] or v['missing_old_paths'] or v['unexpected_paths'])
    def test_new_payload_mismatch_and_absence_do_not_pass(self):
        d=dict(bytes=3,sha256='b'*64)
        for current in ({},{'new':dict(size=2,blob_id='a'*40,lfs=None)}):
            v=self.n['compare_snapshot']({},current,['new'],{'new':d},{'new':'a'*40})
            self.assertFalse(v['all_created_payload_byte_identities_exact'])
    def test_exact_attribute_append_is_distinct_from_rewrite_or_removal(self):
        old=b'*.pt filter=lfs diff=lfs merge=lfs -text\n'
        line=(self.n['CHECKPOINT']+' filter=lfs diff=lfs merge=lfs -text\n').encode()
        v=self.n['classify_attributes'](old,old+line)
        self.assertTrue(v['exact_checkpoint_LFS_rule_append']);self.assertEqual(v['removed_line_count'],0);self.assertEqual(v['added_line_count'],1)
        for new in (line,old+line+b'# other\n',old):self.assertFalse(self.n['classify_attributes'](old,new)['exact_checkpoint_LFS_rule_append'])
    def test_finite_five_metadata_and_two_forced_attributes_calls_only(self):
        main=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='main');text=ast.unparse(main)
        self.assertEqual(self.n['REQUESTED'],(self.n['BASELINE'],self.n['FIRST'],self.n['SECOND'],self.n['PARTIAL'],'main'))
        self.assertEqual(text.count('api.model_info('),1);self.assertEqual(text.count('hf_hub_download('),1)
        self.assertIn('force_download=True',text)
        self.assertNotIn('create_commit',text);self.assertNotIn('CommitOperation',text)
        self.assertLess(text.index('h.clean(gate'),text.index('import huggingface_hub'))
    def test_no_checkpoint_open_or_prediction_JSON_parse(self):
        text=SOURCE.read_text()
        self.assertIn('if name==CHECKPOINT:continue',text)
        self.assertIn('checkpoint_opened=False',text)
        self.assertIn('strict_publication_invariants_passed=partial',text)
        self.assertNotIn('json.loads',text);self.assertNotIn('subprocess',text)
    def test_source_helper_executes_exact_checked_buffer(self):
        fn=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='helper');text=ast.unparse(fn)
        self.assertLess(text.index('hashlib.sha256(raw).hexdigest() == HELPER_SHA256'),text.index('exec(compile(raw'))
        self.assertNotIn('SourceFileLoader',text)

if __name__=='__main__':unittest.main(verbosity=2)
