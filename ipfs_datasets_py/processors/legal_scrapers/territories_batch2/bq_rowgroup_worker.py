"""One row group per short-lived process; bounded Arrow buffers and no deletes."""
import pathlib,json,sys,resource
from batch2_common import ROOT,guard,install_guard
install_guard();guard(True)
import pyarrow as pa,pyarrow.parquet as pq,pyarrow.compute as pc
kind=sys.argv[1];group=int(sys.argv[2]);ids=set(json.load((ROOT/'BQ_selected_ids.json').open()));src=pathlib.Path('/workspace/legal-corpora/nl_extract/hub_verify_58982353b51d/data')/(kind+'.parquet');pf=pq.ParquetFile(src,pre_buffer=False,buffer_size=0);table=pf.read_row_group(group,use_threads=False);guard()
mask=pc.is_in(table['id' if kind=='laws' else 'law_id'],value_set=pa.array(sorted(ids)));table=table.filter(mask);guard()
if len(table):
 if kind=='laws':
  for col in ['jurisdiction','country']:
   table=table.set_column(table.schema.get_field_index(col),col,pa.array(['BQ']*len(table)))
 table=table.append_column('jurisdiction_code',pa.array(['BQ']*len(table))).append_column('parent_country',pa.array(['NL']*len(table)))
 target=ROOT/'BQ/rowgroup_shards'/kind/f'{group:03}.parquet';target.parent.mkdir(parents=True,exist_ok=True);pq.write_table(table,target,compression='zstd');print('BQ_SHARD',kind,group,len(table),flush=True)
print('PEAK_RSS_MB',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,flush=True)
