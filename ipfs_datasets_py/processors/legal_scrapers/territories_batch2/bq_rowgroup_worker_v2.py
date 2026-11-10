import sys,pathlib,json,resource
from batch2_common import ROOT,guard,install_guard
install_guard();guard(True)
import pyarrow as pa,pyarrow.parquet as pq,pyarrow.compute as pc
kind=sys.argv[1];g=int(sys.argv[2]);idfile='BQ_verified_law_ids.json' if kind=='articles' else 'BQ_candidate_ids.json';ids=json.load((ROOT/idfile).open());source=pathlib.Path('/workspace/legal-corpora/nl_extract/hub_verify_58982353b51d/data')/(kind+'.parquet');pf=pq.ParquetFile(source,pre_buffer=False,buffer_size=0);t=pf.read_row_group(g,use_threads=False);guard();mask=pc.is_in(t['law_id' if kind=='articles' else 'id'],value_set=pa.array(ids));mask=pc.and_(mask,pc.greater_equal(pc.utf8_length(t['text']),50 if kind=='laws' else 1));t=t.filter(mask);guard()
if len(t):
 if kind=='laws':
  for col in ['jurisdiction','country']:t=t.set_column(t.schema.get_field_index(col),col,pa.array(['BQ']*len(t)))
 t=t.append_column('jurisdiction_code',pa.array(['BQ']*len(t))).append_column('parent_country',pa.array(['NL']*len(t)));p=ROOT/'BQ/rowgroup_shards_v2'/kind/f'{g:03}.parquet';p.parent.mkdir(parents=True,exist_ok=True);pq.write_table(t,p,compression='zstd');print('SHARD',kind,g,len(t),flush=True)
print('PEAK_RSS_MB',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
