"""At most three immediate qualified check/sample pairs; exact joins or refusal.

Reads only public metadata and private RECEIPT metadata. Endpoint bodies are
read solely by the unchanged qualified guardian and sampler children.
"""
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

F=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
SAMPLER=F/'sample_actor_refinement_private_resources_v01.py'
SAMPLER_SHA256='12198ff14d97be98490b934e1e96010e74721424a94bef861665a77a2008eadc'
_raw=SAMPLER.read_bytes()
if len(_raw)!=6669 or hashlib.sha256(_raw).hexdigest()!=SAMPLER_SHA256:
    raise ValueError('exact qualified sampler helper source required')
_spec=importlib.util.spec_from_file_location('qualified_opening_sampler_helpers',SAMPLER)
s=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(s)
OUTPUT=F/'resource-collection-v02.json'
INPUTS=F/'resource-baseline-inputs-v03.json'
QUALIFICATION=F/'resource-collection-source-independent-review-v02.json'
POLICY=F/'resource-observation-policy-v01.json'
POLICY_PIN=dict(path=str(POLICY),bytes=7483,sha256='ffe18e9590520124be6620358723bb108ca40d14c436f8a544f658241401e184')


def write_public(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    path.chmod(0o444);return s.brief(s.pin(path))


def endpoint_matches(check,receipt):
    """Only exact bytes/SHA pairs; occupancy is never required to be empty."""
    out={}
    for name,key in (('ledger','disk_ledger'),('scheduler','shared_state')):
        a={field:check[key][field] for field in ('bytes','sha256')}
        b={field:receipt[name][field] for field in ('bytes','sha256')}
        s.require(type(a['bytes']) is int and type(b['bytes']) is int and a['bytes']>0 and b['bytes']>0
            and type(a['sha256']) is str and type(b['sha256']) is str and len(a['sha256'])==len(b['sha256'])==64,
            'typed bounded endpoint descriptors required')
        out[name]=dict(check=a,sample=b,exact_match=a==b)
    return out


def qualified_receipt(descriptor,index):
    path=F/'private-runtime-snapshots'/('opening-v'+str(index).zfill(2))/'snapshot-receipt-v01.json'
    s.require(set(descriptor)=={'path','bytes','sha256'} and descriptor['path']==str(path)
        and s.brief(s.pin(path))==descriptor,'exact qualified child receipt descriptor required')
    for directory in (path.parent.parent,path.parent):
        s.require(directory.resolve(strict=True)==directory and not directory.is_symlink()
            and stat.S_IMODE(directory.stat().st_mode)==0o700,'owned physical private700 directories required')
    s.require(stat.S_IMODE(path.stat().st_mode)==0o400,'owned receipt400 required')
    receipt=s.read(path)
    s.require(receipt['schema']=='actor-refinement-private-endpoints/v1' and receipt['role']=='opening'
        and receipt['cell'] is None and receipt['index']==index,'true selected opening role/index required')
    for name,endpoint in (('ledger',s.LEDGER),('scheduler',s.SCHEDULER)):
        s.require(receipt[name]['path']==str(path.parent/(name+'.json'))
            and receipt['source_'+name]['path']==str(endpoint)
            and all(receipt[name][field]==receipt['source_'+name][field] for field in ('bytes','sha256')),
            'receipt must bind unchanged qualified endpoint-copy descriptors')
    return receipt


def main():
    s.require(sys.argv[1:]==[] and not any(os.path.lexists(path) for path in (OUTPUT,INPUTS)),
        'argument-free exclusive bounded collection required')
    own=s.brief(s.pin(Path(__file__).resolve()));q=s.read(QUALIFICATION)
    s.require(q['schema']=='actor-refinement-resource-collection-source-independent-review/v1'
        and q['passed'] is True and q['findings']==[] and q['collector']==own,'exact independent collector source gate required')
    for path,item in q['artifacts'].items():s.require(s.brief(s.pin(path))==dict(path=path,**{key:item[key] for key in ('bytes','sha256')}),'qualified source artifact drift')
    s.require(s.brief(s.pin(POLICY))==POLICY_PIN,'exact qualified observation policy required');policy=s.read(POLICY)
    for name,key,schema in (('sampler-source-independent-review-v01.json','sampler','actor-refinement-sampler-source-independent-review/v1'),
                            ('resource-bridge-source-independent-review-v01.json','guardian','actor-refinement-resource-bridge-source-independent-review/v1')):
        value=s.read(F/name)
        s.require(value['schema']==schema and value['passed'] is True and value['findings']==[] and value[key]==policy[key],
            'exact qualified existing child required')
        s.require(s.brief(s.pin(policy[key]['path']))==policy[key],'child source rawpin changed')
    attempts=[];selected=None
    # No wait, model, admission, census or mutation retry. Only mismatched byte pairs repeat.
    for index in (5,6,7):
        check_path=F/('guardian-check-v'+str(index).zfill(2)+'.json')
        receipt_path=F/'private-runtime-snapshots'/('opening-v'+str(index).zfill(2))/'snapshot-receipt-v01.json'
        s.require(not os.path.lexists(check_path) and not os.path.lexists(receipt_path.parent),'fresh retained collection index required')
        entry=dict(index=index,check=None,sample_receipt=None,matched=False)
        try:
            try:
                with check_path.open('xb') as stream:
                    try:
                        result=subprocess.run([sys.executable,'-B',policy['guardian']['path'],'--check'],cwd=F,
                            stdout=stream,stderr=subprocess.PIPE,timeout=15,check=False)
                    finally:stream.flush();os.fsync(stream.fileno())
            finally:
                if check_path.exists():check_path.chmod(0o444)
            entry.update(check=s.brief(s.pin(check_path)),check_returncode=result.returncode,
                check_stderr_bytes=len(result.stderr),check_stderr_sha256=hashlib.sha256(result.stderr).hexdigest())
            s.require(result.returncode==0,'qualified check failed; no blind retry')
            # Deliberately no model/tool turn or state inspection between the children.
            result=subprocess.run([sys.executable,'-B',str(SAMPLER),'--role','opening','--index',str(index)],cwd=F,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,check=False)
            entry.update(sampler_returncode=result.returncode,sampler_stderr_bytes=len(result.stderr),
                sampler_stderr_sha256=hashlib.sha256(result.stderr).hexdigest())
            s.require(result.returncode==0 and len(result.stdout)<=65536,'qualified sampler failed; no blind retry')
            message=json.loads(result.stdout);s.require(message['status']=='private_sampled_endpoints_copied','exact child completion metadata required')
            entry['sample_receipt']=message['receipt'];receipt=qualified_receipt(message['receipt'],index)
            check=s.read(check_path)
            s.require(check['passed'] is True and check['findings']==[],'successful public compatibility check required')
            matches=endpoint_matches(check,receipt);entry['endpoints']=matches;entry['matched']=all(row['exact_match'] for row in matches.values())
            attempts.append(entry)
            if entry['matched']:
                selected=entry;break
        except (ValueError,KeyError,TypeError,OSError,subprocess.TimeoutExpired,json.JSONDecodeError) as error:
            if entry['check'] is None and check_path.exists():entry['check']=s.brief(s.pin(check_path))
            entry.update(collection_error_type=type(error).__name__,collection_error=str(error) if isinstance(error,ValueError) else 'bounded child/metadata refusal')
            attempts.append(entry);break
    input_pin=None
    if selected is not None:
        value=dict(schema='actor-refinement-resource-baseline-inputs/v1',policy=POLICY_PIN,
            sample_receipt=selected['sample_receipt'],check=selected['check'],
            sampler_qualification=s.brief(s.pin(F/'sampler-source-independent-review-v01.json')),
            bridge_qualification=s.brief(s.pin(F/'resource-bridge-source-independent-review-v01.json')))
        input_pin=write_public(INPUTS,value)
    for path,expected in s.READ_PINS.items():s.require(s.pin(path)==expected,'consumed public/receipt metadata drift')
    s.require(s.brief(s.pin(Path(__file__).resolve()))==own,'collector source drift')
    value=dict(schema='actor-refinement-resource-collection/v1',passed=selected is not None,
        findings=[] if selected is not None else ['no matching qualified endpoint pair within fixed collection bound'],
        observed_at_utc=datetime.now(timezone.utc).isoformat(),collector=own,source_qualification=s.brief(s.pin(QUALIFICATION)),
        policy=POLICY_PIN,max_pairs=3,permitted_indices=[5,6,7],actual_pair_count=len(attempts),attempts=attempts,
        selected_index=None if selected is None else selected['index'],selected_input_manifest=input_pin,
        all_attempt_evidence_retained=True,joins_weakened=False,private_receipt_metadata_only=True,
        private_endpoint_bodies_parsed=0,model_calls=0,admission_calls=0,resource_API_calls=0,actual_censuses=0,
        global_state_writes=0,new_claims=0,locks_acquired=0,assumed_idle=False,observer_main_calls=0)
    print(json.dumps(write_public(OUTPUT,value),sort_keys=True))


if __name__=='__main__':main()
