"""Small real tar/gzip fixtures only; never read historical result/archive bodies."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest

SOURCE=Path(__file__).with_name('restore_owned_results_archive_v01.py')
spec=importlib.util.spec_from_file_location('restore_fixture_only',SOURCE)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def sha(raw):return hashlib.sha256(raw).hexdigest()
def descriptor(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=sha(raw))

def fixture(root,*,tar_mutation=None,manifest_mutation=None):
    payloads={'attempt-fixture-a/results/checkpoint.json':b'OPAQUE not JSON\x00\xff',
        'attempt-fixture-a/results/nested/'+('long-name-'*8)+'scores.bin':b'\x00\x01\x02'*31,
        'attempt-fixture-b/results/empty.bin':b''}
    records=[]
    for index,(name,raw) in enumerate(payloads.items()):
        records.append(dict(path=str(r.RUN/name),member=name,bytes=len(raw),sha256=sha(raw),mode=(0o444,0o600,0o664)[index],
            uid=os.getuid(),gid=os.getgid(),mtime_ns=1700000000000000000,atime_ns=1700000000000000000,ctime_ns=1700000000000000000,device=1,inode=index+10))
    archive=root/'archive.tar.gz'
    members=[]
    for row in records:
        item=tarfile.TarInfo(row['member']);item.mode=row['mode'];item.uid=row['uid'];item.gid=row['gid'];item.mtime=row['mtime_ns']//1000000000;item.size=row['bytes'];members.append((item,payloads[row['member']]))
    if tar_mutation:tar_mutation(members)
    with archive.open('xb') as output:
        with gzip.GzipFile(filename='',mode='wb',fileobj=output,mtime=0) as compressed:
            with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.PAX_FORMAT) as tar:
                for item,raw in members:tar.addfile(item,io.BytesIO(raw) if item.isreg() else None)
    directory_names={'attempt-fixture-a/results','attempt-fixture-a/results/nested','attempt-fixture-a/results/empty-dir','attempt-fixture-b/results'}
    manifest=dict.fromkeys(r.MANIFEST_KEYS,0)
    stub=dict(path=str(root/'public-source'),bytes=1,sha256='a'*64)
    manifest.update(schema='actor-refinement-owned-results-archive-prepared/v1',passed=True,findings=[],producer=dict(stub,bytes=16909,sha256=r.PREPARER_SHA256),intake=stub,source_qualification=stub,archive=descriptor(archive),
        protected_attempts=sorted(r.PROTECTED),excluded_ambiguous_attempts=sorted(r.EXCLUDED),originals_modified=False,cap_changed=False,native_capacity_PASS_claimed=False,training_authorized=False,
        apply_requires_separate_actual_concrete_review=True,restoration_preserves_raw_bytes_mode_but_not_original_inode_ctime=True,final_archive_must_remain_inside_counted_root=True,source_archive_temporary_outside_counted_roots=True,
        originals=records,file_count=len(records),raw_bytes=sum(len(v) for v in payloads.values()),actual_archive_bytes=archive.stat().st_size,
        qualified_ownership=dict.fromkeys(('attempt-fixture-a','attempt-fixture-b'),{}),preserved_directories=[dict(path=str(r.RUN/name),device=1,inode=i+1,mode=0o750) for i,name in enumerate(sorted(directory_names))])
    if manifest_mutation:manifest_mutation(manifest)
    path=root/'manifest.json';path.write_text(json.dumps(manifest,sort_keys=True)+'\n')
    return path,archive,payloads,manifest

def call(path,archive,**kwargs):
    p=descriptor(path);return r.restore_archive(path,manifest_bytes=p['bytes'],manifest_sha256=p['sha256'],archive_path=archive,**kwargs)

class RestoreControls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='owned-restore-fixture-');self.root=Path(self.temp.name);self.original_f=r.F;r.F=self.root
    def tearDown(self):r.F=self.original_f;self.temp.cleanup()
    def test_default_verify_is_readonly_opaque_and_supports_stdlib_PAX(self):
        path,archive,payloads,manifest=fixture(self.root);before={p.name:descriptor(p) for p in self.root.iterdir()}
        result=call(path,archive)
        self.assertEqual(result['mode'],'verify-only');self.assertEqual(result['verified'],dict(member_count=3,raw_bytes=sum(map(len,payloads.values()))))
        self.assertEqual({p.name:descriptor(p) for p in self.root.iterdir()},before);self.assertEqual(result['materialized_file_count'],0);self.assertFalse(result['original_paths_opened']);self.assertFalse(result['original_inode_ctime_restored'])
    def test_selected_materialization_bytes_modes_empty_dirs_and_no_overwrite(self):
        path,archive,payloads,manifest=fixture(self.root);stage=self.root/'fresh-stage';before=(descriptor(path),descriptor(archive))
        result=call(path,archive,materialize=True,selected_attempts=['attempt-fixture-a'],stage=stage)
        self.assertEqual(result['materialized_file_count'],2);self.assertTrue(result['file_bytes_and_modes_readback_verified'])
        for row in manifest['originals']:
            target=stage/row['member']
            if row['member'].startswith('attempt-fixture-a/'):
                self.assertEqual(target.read_bytes(),payloads[row['member']]);self.assertEqual(stat.S_IMODE(target.stat().st_mode),row['mode'])
            else:self.assertFalse(target.exists())
        self.assertEqual(stat.S_IMODE((stage/'attempt-fixture-a/results/empty-dir').stat().st_mode),0o750)
        self.assertEqual(before,(descriptor(path),descriptor(archive)))
        with self.assertRaises(ValueError):call(path,archive,materialize=True,selected_attempts=['attempt-fixture-a'],stage=stage)
        # Unreadable original file modes are set only after the byte readback.
        child=self.root/'zero-mode-input';child.mkdir()
        p,a,_,m=fixture(child,tar_mutation=lambda rows:setattr(rows[0][0],'mode',0),manifest_mutation=lambda m:m['originals'][0].update(mode=0))
        zero_stage=self.root/'zero-mode-stage';call(p,a,materialize=True,selected_attempts=['attempt-fixture-a'],stage=zero_stage)
        self.assertEqual(stat.S_IMODE((zero_stage/m['originals'][0]['member']).stat().st_mode),0)
    def test_raw_manifest_and_archive_identity_refuse_before_any_stage_write(self):
        path,archive,_,_=fixture(self.root);stage=self.root/'never-created'
        with self.assertRaises(ValueError):r.restore_archive(path,manifest_bytes=path.stat().st_size,manifest_sha256='f'*64,archive_path=archive,materialize=True,selected_attempts=['attempt-fixture-a'],stage=stage)
        with archive.open('ab') as out:out.write(b'x')
        with self.assertRaises(ValueError):call(path,archive,materialize=True,selected_attempts=['attempt-fixture-a'],stage=stage)
        self.assertFalse(stage.exists())
    def test_tar_duplicates_links_directories_unknown_members_and_metadata_fail_closed(self):
        mutations=[lambda m:m.append(copy.deepcopy(m[0])),lambda m:setattr(m[0][0],'type',tarfile.SYMTYPE),
            lambda m:setattr(m[0][0],'type',tarfile.LNKTYPE),lambda m:setattr(m[0][0],'type',tarfile.DIRTYPE),
            lambda m:setattr(m[0][0],'name','attempt-fixture-a/results/../escape'),lambda m:setattr(m[0][0],'name','/absolute'),
            lambda m:setattr(m[0][0],'name','attempt-fixture-a/results/unknown'),lambda m:setattr(m[0][0],'mode',0o666),
            lambda m:setattr(m[0][0],'uid',os.getuid()+1),lambda m:m.pop(),lambda m:m.__setitem__(0,(m[0][0],b'X'*len(m[0][1])))]
        for index,mutation in enumerate(mutations):
            with self.subTest(index=index):
                child=self.root/str(index);child.mkdir();path,archive,_,_=fixture(child,tar_mutation=mutation)
                with self.assertRaises((ValueError,tarfile.TarError,EOFError)):call(path,archive)
    def test_manifest_unknown_keys_duplicate_members_bad_paths_shapes_and_bounds_refused(self):
        mutations=[lambda m:m.update(unknown=True),lambda m:m['originals'].append(copy.deepcopy(m['originals'][0])),
            lambda m:m['originals'][0].update(path='/outside/original'),lambda m:m['originals'][0].update(mode=True),
            lambda m:m['originals'][0].update(mode=0o4755),lambda m:m['originals'][0].update(bytes=r.MAX_MEMBER+1),
            lambda m:m.update(raw_bytes=True),lambda m:m['qualified_ownership'].pop('attempt-fixture-b'),
            lambda m:m.update(preserved_directories=[]),lambda m:m.update(original_unlinks=1)]
        for index,mutation in enumerate(mutations):
            with self.subTest(index=index):
                child=self.root/str(index);child.mkdir();path,archive,_,_=fixture(child,manifest_mutation=mutation)
                with self.assertRaises(ValueError):call(path,archive)
    def test_explicit_selection_fresh_owned_stage_and_physical_inputs_required(self):
        path,archive,_,_=fixture(self.root)
        for kwargs in (dict(stage=self.root/'bad'),dict(selected_attempts=['attempt-fixture-a']),dict(materialize=True,stage=self.root/'bad'),
            dict(materialize=True,selected_attempts=['missing'],stage=self.root/'bad'),dict(materialize=True,selected_attempts=['attempt-fixture-a']*2,stage=self.root/'bad'),
            dict(materialize=True,selected_attempts=['attempt-fixture-a'],stage=self.root.parent/'outside-stage')):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):call(path,archive,**kwargs)
        link=self.root/'alias.tar.gz';link.symlink_to(archive)
        with self.assertRaises(ValueError):call(path,link)
        alias=self.root/'hardlink.tar.gz';os.link(archive,alias)
        with self.assertRaises(ValueError):call(path,alias)
    def test_duplicate_manifest_JSON_and_truncated_or_concatenated_archives_refused(self):
        path,archive,_,manifest=fixture(self.root);original=archive.read_bytes()
        path.write_text('{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError,'duplicate'):call(path,archive)
        for index,raw in enumerate((original[:-6],original+gzip.compress(b'not a tar member'))):
            child=self.root/str(index);child.mkdir();path2,archive2,_,m=fixture(child);archive2.write_bytes(raw)
            m['archive']=descriptor(archive2);m['actual_archive_bytes']=len(raw);path2.write_text(json.dumps(m))
            with self.subTest(index=index),self.assertRaises((ValueError,EOFError,tarfile.TarError,OSError)):call(path2,archive2)
    def test_archive_relocation_preserves_content_binding_and_manifest_unmodified(self):
        path,archive,_,_=fixture(self.root);new=self.root/'downloaded.tar.gz';archive.rename(new)
        result=call(path,new);self.assertTrue(result['archive_relocated']);self.assertEqual(result['archive']['sha256'],result['archive_origin_descriptor']['sha256'])

if __name__=='__main__':unittest.main()
