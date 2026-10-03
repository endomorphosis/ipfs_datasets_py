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
        'priming_observation_return':sample('observation0','returned'),
        'replay_sql_before_close':sample('replay_source_connection','before_close'),
        'replay_sql_closed':sample('replay_source_connection','closed'),
        'replay_sql_reopened':sample('replay_source_connection','reopened'),
        'warm_load_enter':sample('load','enter',1),
        'warm_load_return':sample('load','return',1),
        'first_replay_observation_return':sample('observation1','returned'),
        'second_replay_load_enter':sample('load','enter',2),
        'second_replay_load_return':sample('load','return',2),
        'second_replay_observation_return':sample('observation2','returned'),
        'before_close':sample('source_connection','before_close'),
        'after_close':sample('source_connection','after_close'),
    }
    observation_events=[]
    for event in events:
        observation_events.append(event)
        if (event['stage'],event['phase'])==('observation2','returned'):break
    peak=dict(kernel_vm_hwm_bytes=max(row['process']['VmHWM'] for row in observation_events),
        sampled_rss_bytes=max(row['process']['VmRSS'] for row in observation_events),
        sampled_rss_anon_bytes=max(row['process']['RssAnon'] for row in observation_events),
        scope='Through third observation return, before explicit output parity serialization')
    return dict(receipt_sha256=sha(root/'receipt.json'),owner_sha256=receipt['owner_sha256'],selected_producers=receipt['selected_producer_before'],replay_shape=receipt['replay_shape'],
        observed_head=receipt['head'],retained_before=receipt['retained_before'],
        returned_manifest_canonical_sha256=receipt['returned_manifest_canonical_sha256'],
        returned_manifest_cid=receipt['returned_manifest_cid'],
        rounds=receipt['rounds'],seconds=receipt['seconds'],metrics=metrics,peak=peak)

baseline=arm('baseline-02');candidate=arm('candidate-02')
if baseline['observed_head']!=candidate['observed_head'] or baseline['retained_before']!=candidate['retained_before']:
    raise ValueError('paired corpus identity differs')
if baseline['returned_manifest_canonical_sha256']!=candidate['returned_manifest_canonical_sha256']:
    raise ValueError('returned canonical manifest differs')
for row in (baseline,candidate):del row['retained_before']
result=dict(schema='native-manifest-warm-replay-comparison-summary@1',baseline=baseline,candidate=candidate,
    candidate_minus_baseline={key:{metric:candidate['metrics'][key][metric]-baseline['metrics'][key][metric]
        for metric in ('rss_anon_bytes','rss_bytes','allocated_python_blocks','duckdb_bytes')}
        for key in baseline['metrics']},
    source_and_sql_checks_unchanged=True,provider_calls=0,model_loads=0,training_steps=0,
    gc_collect_called=False,malloc_trim_called=False,scheduler_policy_changed=False,
    interpretation='Paired instrumented source-only host observations in fresh processes. One priming observation followed by a source SQL owner close/reopen and two replay observations; the native memo stays intact. This is not Docker admission, model inference, a benchmark reward, or a general scaling result. Retained representation and RSS measure different quantities.')
(B/'comparison-reopened.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('schema','candidate_minus_baseline')}))
