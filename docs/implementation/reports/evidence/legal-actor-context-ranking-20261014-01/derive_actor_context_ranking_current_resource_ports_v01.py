"""Write new current-scheduler resource drafts from exact public source inputs.

Source generation only: no imports of resource/model modules, private reads,
endpoint observations, census, locks, SDK calls or numerical work.
"""
import ast
import hashlib
import json
import os
from pathlib import Path

F=Path(__file__).resolve().parent
CORE={
    'run_scope_guardian_v04.py':(40140,'cadff26b30c65b42f0fd218cae391dcb9bfec5014ac104605860428d33e422b8'),
    'adopt_shared_scheduler_actor_ranking_v03.py':(18825,'573941d4c9dc69445a74b973e2b7966c66a1aa0b220fc31fc4c6335adc86b93b'),
    'owned_lease_watchdog_actor_ranking_v03.py':(27360,'af2847920a5bb184f0e9801e7eabe1eea68029085fc1f1730d8cd682a662ff4b'),
    'bootstrap_actor_context_ranking_resources_v02.py':(6599,'e1847c2723216b4f2a06ee9da80adfeb8121e94e0b2442da0d2f95e2288d7be1'),
}
RETAINED={
    'resource-observation-policy-v01.json':(7532,'d9056253244e653c544b4fee5ac371a3d86a538fa8c67f6330512ec2cd9a90ac'),
    'actor_context_ranking_resource_protocol_v01.py':(20230,'4edb0362eced0670740dc973e921cc09ee6e3e939c1d092fe81626a2a75aa39b'),
    'collect_actor_context_ranking_opening_v01.py':(9580,'9d7ed2f231b5bee4958eefe2129ca12c1f61a8702f938895400b8fb96d738215'),
    'review_actor_context_ranking_resource_baseline_v01.py':(7237,'210280704339a89b4d43a13b3e096271af016c3472634f96e6e9fd1423ffa7f9'),
    'resource-source-snapshot-v01.json':(4678,'fbbbc82c791998e4498a30226cc8f61a17bd7ce46f57229629710631af9761b2'),
    'guardian-config-inspection-v02.json':(14492,'29ee4031d08b3845794978d59571c5867a73a1204d3e861cc909e0685cba4661'),
}


def require(value,message):
    if not value:raise ValueError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def pin(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path and not path.is_symlink(),'Physical source file required')
    raw=path.read_bytes()
    return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def source(name):
    expected=(CORE|RETAINED)[name];item=pin(F/name)
    require((item['bytes'],item['sha256'])==expected,'Exact retained/core source changed: '+name)
    return (F/name).read_text()


def once(text,old,new):
    require(text.count(old)==1,'Unique source anchor required: '+old[:90])
    return text.replace(old,new)


def assignment(text,name,value):
    matches=[n for n in ast.parse(text).body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)]
    require(len(matches)==1,'Exact assignment required: '+name)
    node=matches[0];lines=text.splitlines(keepends=True)
    return ''.join(lines[:node.lineno-1])+name+'='+repr(value)+'\n'+''.join(lines[node.end_lineno:])


def write_new(name,raw):
    path=F/name
    with path.open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
    path.chmod(0o444)
    return pin(path)


def main():
    for name in CORE:source(name)
    old=json.loads(source('resource-observation-policy-v01.json'))
    inspection=json.loads(source('guardian-config-inspection-v02.json'))
    summary=inspection['summary']
    require(summary['unknown_key_count']==0 and summary['config_key_count']==24
        and all(item['value_disclosed'] is True for item in summary['known_fields'].values()),'Exact publicly disclosed current24 config required')
    config={name:item['value'] for name,item in summary['known_fields'].items()}
    config_sha=hashlib.sha256(canonical(config)).hexdigest()
    require(config_sha==summary['config_sha256']=='f07cb14289fcb6275e4497dcc36be0dcf8bfc3dc87531ff7a9537eb85fdcc661','Authenticated full current config differs')
    snapshot=json.loads(source('resource-source-snapshot-v01.json'))
    require(snapshot['file_count']==len(snapshot['files'])==6 and snapshot['actual_imports']==0,'Exact owned six-file source snapshot required')
    producers={}
    for relative,row in snapshot['files'].items():
        item=pin(row['snapshot']['path'])
        require(item==row['snapshot'] and all(item[k]==row['origin'][k] for k in ('bytes','sha256')),'Current source snapshot raw drift')
        producers[item['path']]={k:item[k] for k in ('bytes','sha256')}
    for path,item in old['resource_producer_pins'].items():
        if Path(path).name in {'autoencoder_daemon_resources.py','lazy_scheduler_adoption.py'}:
            require(pin(path)==dict(path=path,**item),'Unchanged native owner/lazy source required')
            producers[path]=item
    for name in ('adopt_shared_scheduler_actor_ranking_v03.py','owned_lease_watchdog_actor_ranking_v03.py'):
        item=pin(F/name);producers[item['path']]={k:item[k] for k in ('bytes','sha256')}
    require(len(producers)==10,'Exact ten named producer roles required')
    bootstrap=pin(F/'bootstrap_actor_context_ranking_resources_v02.py')
    policy=dict(old,guardian=pin(F/'run_scope_guardian_v04.py'),scheduler_config=config,scheduler_config_sha256=config_sha,
        resource_producer_pins=producers,namespace_bootstrap_source=bootstrap,
        current_resource_source_snapshot=pin(F/'resource-source-snapshot-v01.json'),current_config_inspection=pin(F/'guardian-config-inspection-v02.json'),
        named_resource_producer_count=10,total_resource_sources_with_namespace_bootstrap=11,
        shared_config_adopted_without_change=True,old_scheduler_emulation=False)
    require(policy['resources']==old['resources'] and policy['global_cap_bytes']==145000000000
        and policy['counted_root_metadata']==old['counted_root_metadata'],'No envelope/cap/root change allowed')
    policy_raw=(json.dumps(policy,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    policy_pin=dict(path=str(F/'resource-observation-policy-v02.json'),bytes=len(policy_raw),sha256=hashlib.sha256(policy_raw).hexdigest())
    protocol=source('actor_context_ranking_resource_protocol_v01.py')
    protocol=protocol.replace("POLICY=F/'resource-observation-policy-v01.json'","POLICY=F/'resource-observation-policy-v02.json'")
    protocol=assignment(protocol,'POLICY_PIN',policy_pin)
    protocol=assignment(protocol,'POLICY_CANONICAL_SHA256',hashlib.sha256(canonical(policy)).hexdigest())
    protocol=once(protocol,'\n# Exact previously qualified ASTs;', '\nNAMESPACE_BOOTSTRAP_PIN='+repr(bootstrap)+'\n\n# Exact previously qualified ASTs;')
    for before,after in (
        ('review_actor_context_ranking_resource_baseline_v01.py','review_actor_context_ranking_resource_baseline_v02.py'),
        ('resource-observer-source-independent-review-v01.json','resource-observer-source-independent-review-v02.json'),
        ('resource-baseline-inputs-v01.json','resource-baseline-inputs-v02.json'),
        ('resource-bridge-source-independent-review-v01.json','resource-bridge-source-independent-review-v02.json'),
        ('76d10cc42015c9e4cbdad0fabd6a64f706320e14a8fb507f16262d42dd1d5856',config_sha)):
        protocol=protocol.replace(before,after)
    protocol=once(protocol,"    return dict(schema_version=state['schema_version']", "    require(check['namespace_bootstrap_source']==policy['namespace_bootstrap_source']==NAMESPACE_BOOTSTRAP_PIN,\n        'Exact separately authenticated eleventh resource bootstrap source required')\n    return dict(schema_version=state['schema_version']")
    protocol=once(protocol,"    ledger=baseline['baseline_ledger'];actual=ledger['record_body_hashes'];extra=ledger['additional_current_record_body_hashes']",
        "    require(baseline['namespace_bootstrap_source']==NAMESPACE_BOOTSTRAP_PIN\n        and baseline['artifacts'].get(NAMESPACE_BOOTSTRAP_PIN['path'])==NAMESPACE_BOOTSTRAP_PIN,\n        'All eleven actual resource sources including the namespace bootstrap must be admitted')\n    ledger=baseline['baseline_ledger'];actual=ledger['record_body_hashes'];extra=ledger['additional_current_record_body_hashes']")
    collector=source('collect_actor_context_ranking_opening_v01.py')
    for before,after in (
        ('resource-collection-v01.json','resource-collection-v02.json'),('resource-baseline-inputs-v01.json','resource-baseline-inputs-v02.json'),
        ('resource-collection-source-independent-review-v01.json','resource-collection-source-independent-review-v02.json'),
        ('resource-observation-policy-v01.json','resource-observation-policy-v02.json'),
        ('resource-bridge-source-independent-review-v01.json','resource-bridge-source-independent-review-v02.json'),
        ('for index in (1,2,3):','for index in (3,4,5):'),('permitted_indices=[1,2,3]','permitted_indices=[3,4,5]')):
        collector=collector.replace(before,after)
    collector=assignment(collector,'POLICY_PIN',policy_pin)
    observer=source('review_actor_context_ranking_resource_baseline_v01.py')
    for before,after in (
        ('actor_context_ranking_resource_protocol_v01.py','actor_context_ranking_resource_protocol_v02.py'),
        ('resource-baseline-inputs-v01.json','resource-baseline-inputs-v02.json'),('capacity-refusal-v01.json','capacity-refusal-v02.json'),
        ('resource-observer-source-independent-review-v01.json','resource-observer-source-independent-review-v02.json'),
        ('resource-bridge-source-independent-review-v01.json','resource-bridge-source-independent-review-v02.json')):
        observer=observer.replace(before,after)
    observer=once(observer,'    receipt,ledger,state=p.snapshot(m,inputs[\'sample_receipt\'],policy)',
        "    namespace_pin=policy['namespace_bootstrap_source'];m.pin(namespace_pin['path'],namespace_pin)\n    snapshot_pin=policy['current_resource_source_snapshot'];m.pin(snapshot_pin['path'],snapshot_pin)\n    receipt,ledger,state=p.snapshot(m,inputs['sample_receipt'],policy)")
    observer=once(observer,"        qualified_local_guardian=policy['guardian'],resource_bridge_source_qualification=inputs['bridge_qualification'],",
        "        qualified_local_guardian=policy['guardian'],resource_bridge_source_qualification=inputs['bridge_qualification'],\n        namespace_bootstrap_source=namespace_pin,current_resource_source_snapshot=snapshot_pin,")
    outputs={'resource-observation-policy-v02.json':policy_raw,'actor_context_ranking_resource_protocol_v02.py':protocol.encode(),
        'collect_actor_context_ranking_opening_v02.py':collector.encode(),'review_actor_context_ranking_resource_baseline_v02.py':observer.encode()}
    for name,raw in outputs.items():
        require(not (F/name).exists(),'Never overwrite a draft: '+name)
        if name.endswith('.py'):ast.parse(raw,filename=name)
    written={name:write_new(name,raw) for name,raw in outputs.items()}
    print(json.dumps(dict(status='unqualified_source_drafts_only',outputs=written,model_calls=0,private_body_reads=0,resource_API_calls=0)))


if __name__=='__main__':main()
