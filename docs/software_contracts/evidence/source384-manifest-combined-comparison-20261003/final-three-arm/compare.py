"""Aggregate paired native diagnostic receipts; no task contents are emitted."""
from pathlib import Path
import hashlib,json

B=Path(__file__).parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def arm(label):
    root=B/label
    receipt=json.loads((root/'receipt.json').read_text())
    events=[json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
    if sha(root/'events.jsonl')!=receipt['events_sha256']:
        raise ValueError('event digest differs')
    if not (receipt['status']=='passed' and receipt['retained_unchanged']
            and receipt['owner_unchanged'] and receipt['native_producer_guard_recognized']):
        raise ValueError('paired successful native receipts required')
    def sample(stage,phase,number=0):
        value=[row for row in events if (row['stage'],row['phase'])==(stage,phase)][number]
        return dict(elapsed_seconds=value['elapsed_seconds'],rss_anon_bytes=value['process']['RssAnon'],
            rss_bytes=value['process']['VmRSS'],allocated_python_blocks=value['allocated_python_blocks'],
            duckdb_bytes=sum(row['memory_usage_bytes'] for row in value['duckdb_memory']),
            memo=value['manifest_memo'])
    metrics={
        'before_connection':sample('process','before_connection'),
        'cold_load_enter':sample('load','enter'),
        'cold_load_return':sample('load','return'),
        'first_observation_return':sample('observation0','returned'),
        'first_reference_deleted':sample('observation0','reference_deleted'),
        'second_observation_enter':sample('observation1','enter'),
        'warm_load_enter':sample('load','enter',1),
        'warm_load_return':sample('load','return',1),
        'second_observation_return':sample('observation1','returned'),
        'before_close':sample('source_connection','before_close'),
        'after_close':sample('source_connection','after_close'),
    }
    observation_events=[]
    for event in events:
        observation_events.append(event)
        if (event['stage'],event['phase'])==('observation1','returned'):break
    peak=dict(kernel_vm_hwm_bytes=max(row['process']['VmHWM'] for row in observation_events),
        sampled_rss_bytes=max(row['process']['VmRSS'] for row in observation_events),
        sampled_rss_anon_bytes=max(row['process']['RssAnon'] for row in observation_events),
        scope='Through second observation return, before explicit output parity serialization')
    return dict(receipt_sha256=sha(root/'receipt.json'),owner_sha256=receipt['owner_sha256'],selected_producers=receipt['selected_producer_before'],replay_shape=receipt['replay_shape'],
        observed_head=receipt['head'],retained_before=receipt['retained_before'],
        returned_manifest_canonical_sha256=receipt['returned_manifest_canonical_sha256'],
        returned_manifest_cid=receipt['returned_manifest_cid'],
        rounds=receipt['rounds'],seconds=receipt['seconds'],metrics=metrics,peak=peak)


labels=('baseline-01','byte-only-01','combined-01')
values={label:arm(label) for label in labels}
reference=values[labels[0]]
for value in values.values():
    if (value['observed_head']!=reference['observed_head']
            or value['retained_before']!=reference['retained_before']
            or value['returned_manifest_canonical_sha256']!=reference['returned_manifest_canonical_sha256']):
        raise ValueError('source or canonical output parity differs')
for value in values.values():del value['retained_before']
result=dict(schema='native-final-manifest-three-arm-comparison@1',arms=values,
    candidate_minus_baseline={label:{key:{metric:values[label]['metrics'][key][metric]-reference['metrics'][key][metric]
        for metric in ('rss_anon_bytes','rss_bytes','allocated_python_blocks','duckdb_bytes')}
        for key in reference['metrics']} for label in labels[1:]},
    source_and_sql_checks_unchanged=True,provider_calls=0,model_loads=0,training_steps=0,
    observations_retained_across_rounds=False,explicit_output_parity_only_after_final_return=True,
    gc_collect_called=False,malloc_trim_called=False,scheduler_policy_changed=False,
    interpretation='Same two-observation source-only host profile in three fresh processes. Model/preparation report lifetimes are absent. Actual full pipeline admission remains unqualified by these component measurements; no general scaling or benchmark claim.')
(B/'comparison.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({label:values[label]['rounds'] for label in labels}))
