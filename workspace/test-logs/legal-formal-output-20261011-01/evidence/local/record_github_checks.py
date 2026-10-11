"""Save read-only GitHub check state and failure annotations for one pinned PR head."""
from pathlib import Path
import argparse,subprocess,json,os

def get(*args):return json.loads(subprocess.check_output(['gh',*args]))
def main():
 p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--pr',type=int,required=True);p.add_argument('--head',required=True);p.add_argument('--output',required=True);a=p.parse_args();owner,name=a.repo.split('/')
 pr=get('pr','view',str(a.pr),'--repo',a.repo,'--json','number,state,headRefOid,baseRefName,mergeable,mergeStateStatus,url');assert pr['headRefOid']==a.head
 query='query { repository(owner: '+json.dumps(owner)+', name: '+json.dumps(name)+') { pullRequest(number: '+str(a.pr)+') { commits(last: 1) { nodes { commit { oid statusCheckRollup { contexts(first: 100) { nodes { ... on CheckRun { name status conclusion isRequired(pullRequestNumber: '+str(a.pr)+') detailsUrl } ... on StatusContext { context state isRequired(pullRequestNumber: '+str(a.pr)+') targetUrl } } } } } } } } } }'
 gql=get('api','graphql','-f','query='+query);commit=gql['data']['repository']['pullRequest']['commits']['nodes'][0]['commit'];assert commit['oid']==a.head
 checks=get('api','repos/'+a.repo+'/commits/'+a.head+'/check-runs');assert checks['total_count']==len(checks['check_runs'])<=100
 annotations={str(v['id']):get('api','repos/'+a.repo+'/check-runs/'+str(v['id'])+'/annotations') for v in checks['check_runs'] if v['conclusion']=='failure'}
 nodes=commit['statusCheckRollup']['contexts']['nodes'] if commit['statusCheckRollup'] else []
 assert len(nodes)==checks['total_count'] and all(v['isRequired'] is False for v in nodes)
 v={'schema':'structured-github-check-observation/v1','repo':a.repo,'pr':pr,'head':a.head,'graphql':gql,'check_runs':checks,'failure_annotations':annotations,'all_observed_checks_optional':True,'hosted_ci_passed':False,'observation_only_no_merge_or_check_override':True}
 with Path(a.output).open('x') as s:json.dump(v,s,indent=2,sort_keys=True);s.write('\n');s.flush();os.fsync(s.fileno())
 print(json.dumps({'head':a.head,'checks':len(nodes),'states':[(n.get('name',n.get('context')),n.get('status',n.get('state')),n.get('conclusion')) for n in nodes],'annotation_messages':sorted(set(x['message'] for arr in annotations.values() for x in arr))},indent=2))
if __name__=='__main__':main()
