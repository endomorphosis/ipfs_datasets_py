"""Keep the originally published bytes for parquet files whose content did not change; rebuild MANIFEST; list changes."""
import os,shutil,hashlib,subprocess,json
import pyarrow.parquet as pq
S='/workspace/courts/hf_stage/dataset'; O='/workspace/courts/hf_stage/fix1/dataset'
for dp,_,fn in os.walk(O+'/data'):
    for f in fn:
        o=os.path.join(dp,f); s=os.path.join(S,os.path.relpath(o,O))
        if pq.read_table(o).equals(pq.read_table(s)) and pq.read_metadata(o).schema.to_arrow_schema().metadata==pq.read_metadata(s).schema.to_arrow_schema().metadata:
            shutil.copyfile(s,o); print('kept original bytes:',os.path.relpath(o,O))
os.chdir(O)
files=sorted(os.path.join(dp,f)[2:] for dp,_,fn in os.walk('.') for f in fn if f!='MANIFEST.sha256')
sha=lambda p:hashlib.sha256(open(p,'rb').read()).hexdigest()
open('MANIFEST.sha256','w').write(''.join(f'{sha(p)}  ./{p}\n' for p in files))
allf=files+['MANIFEST.sha256']
chg=[p for p in allf if not os.path.exists(f'{S}/{p}') or sha(p)!=sha(f'{S}/{p}')]
json.dump({'files_total':len(allf),'would_change':chg,'unchanged':[p for p in allf if p not in chg]},open('/workspace/courts/hf_stage/fix1/CHANGE_LIST.json','w'),indent=1)
print(len(chg),'files would change:');print('\n'.join(chg))
