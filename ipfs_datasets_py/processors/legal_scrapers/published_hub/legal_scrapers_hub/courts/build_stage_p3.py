import shutil,os,json,sys
N='/workspace/courts/normalized/phase3'; D='/workspace/courts/hf_stage/dataset'
free=shutil.disk_usage('/workspace').free/2**30
if free<22: sys.exit('STOP disk')
for t in ['court','rule','form','judge']:
    os.makedirs(f'{D}/data/phase3/{t}',exist_ok=True); shutil.copyfile(f'{N}/{t}/part-0000.parquet',f'{D}/data/phase3/{t}/part-0000.parquet')
shutil.copyfile(f'{N}/VALIDATION.json',f'{D}/VALIDATION_phase3.json')
v=json.load(open(f'{N}/VALIDATION.json'))
c=json.load(open(f'{D}/PUBLISH_COUNTS.json'))
rm={}
for r in v['removed']: rm[r['type']]=rm.get(r['type'],0)+r['rows']
for t in ['court','rule','form','judge']:
    c['rows'][f'phase3/{t}']={'in':v['in_by_type'][t],'out':v['out_by_type'][t]}
for r in v['removed']: c['removed'].append({'phase':'phase3',**r})
c['phase3']={'wayback_only_rows':v['wayback_only_rows'],'best_effort_judge_rows':v['best_effort_judge_rows'],'redactions':v['redactions'],'manifest_entries':v['manifest_entries'],'zero_canlii_austlii_cornell':True}
json.dump(c,open(f'{D}/PUBLISH_COUNTS.json','w'),indent=1)
print(c['rows'])
