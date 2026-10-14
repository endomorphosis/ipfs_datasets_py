"""Rebind the unchanged scientific recipe to reviewed current resource sources.

Writes unqualified source drafts only; never imports a producer or reads data,
checkpoints, references, private endpoints or runtime bodies.
"""
import ast
import hashlib
import os
from pathlib import Path

F=Path(__file__).resolve().parent
PINS={
 'run_actor_context_ranking_v03.py':(40395,'62dff1e7626f34a3a29e96374f92fce732fc079eff03ee5c44a5858e98e858f2'),
 'prepare_actor_context_ranking_v03.py':(13530,'7b0d9893bb164a5ed9b01ca0626b54ddb385fabcb40af1dbb57f7dc059c6e474'),
 'actor_context_ranking_bootstrap_smoke_controls_v03.py':(7150,'4a2c1aed786af33046d9c20ec4f0d3376feb8c86dfee345ee23e23b53491a1d6'),
 'review_actor_context_ranking_training_plan_v02.py':(9248,'5d2b02a917c6c5fd2576b5056592b8fb8c23098c5fc562ef8b12b3c5518c609b'),
 'audit_actor_context_ranking_terminal_resources_v03.py':(18600,'fe75cc8fbab28032c967b841b93853a7b3080a7025ac8b943b1900f312b6637f'),
 'freeze_actor_context_ranking_outputs_v03.py':(20530,'8b147e6adb9bf98103389c47d6673c61b32a590cfe71c57d26fc55c5c5ab5165'),
}


def require(value,message):
 if not value:raise ValueError(message)


def retained(name):
 raw=(F/name).read_bytes();require((len(raw),hashlib.sha256(raw).hexdigest())==PINS[name],'Retained source drift: '+name)
 return raw.decode()


def once(source,old,new):
 require(source.count(old)==1,'Unique source anchor required: '+old[:80])
 return source.replace(old,new)


def rebind(source):
 for old,new in (
  ('run_actor_context_ranking_v03.py','run_actor_context_ranking_v04.py'),
  ('prepare_actor_context_ranking_v03.py','prepare_actor_context_ranking_v04.py'),
  ('actor_context_ranking_bootstrap_smoke_controls_v03.py','actor_context_ranking_bootstrap_smoke_controls_v04.py'),
  ('actor-context-ranking-bootstrap-smoke-controls-v03.json','actor-context-ranking-bootstrap-smoke-controls-v04.json'),
  ('run_scope_guardian_v02.py','run_scope_guardian_v04.py'),
  ('actor_context_ranking_resource_protocol_v01.py','actor_context_ranking_resource_protocol_v03.py'),
  ('runner-preparer-source-independent-review-v01.json','runner-preparer-source-independent-review-v02.json'),
  ('actor-context-ranking-terminal-resource-source-independent-review-v01.json','actor-context-ranking-terminal-resource-source-independent-review-v02.json'),
  ('runtime-freeze-source-independent-review-v01.json','runtime-freeze-source-independent-review-v02.json'),
  ('audit_actor_context_ranking_terminal_resources_v03.py','audit_actor_context_ranking_terminal_resources_v04.py')):
  source=source.replace(old,new)
 return source


def raw_loader(source,old,path_expression,local_name,label,raw):
 """Replace one SourceFileLoader invocation with exact-buffer compilation."""
 line=next(line for line in source.splitlines() if old.splitlines()[0].strip()==line.strip())
 indent=line[:len(line)-len(line.lstrip())]
 block='\n'.join(indent+x if x else '' for x in [
  '_checked_path='+path_expression,
  '_checked_raw=_checked_path.read_bytes()',
  'if len(_checked_raw)!='+str(len(raw))+' or hashlib.sha256(_checked_raw).hexdigest()!='+repr(hashlib.sha256(raw).hexdigest())+':',
  "    raise ValueError('Exact metadata helper source required before execution')",
  local_name+'=types.ModuleType('+repr(label)+')',
  local_name+".__file__=str(_checked_path);"+local_name+".__package__=''",
  "exec(compile(_checked_raw,str(_checked_path),'exec',dont_inherit=True),"+local_name+'.__dict__)',
 ])
 return once(source,old,block)


def main():
 runner=rebind(retained('run_actor_context_ranking_v03.py'))
 runner=once(runner,'import time\n','import time\nimport types\n')
 runner=once(runner,"    spec = importlib.util.spec_from_file_location('retained_actor_boundary_helpers', LEGACY_RUNNER)\n    module = importlib.util.module_from_spec(spec)\n    spec.loader.exec_module(module)",
  "    raw=LEGACY_RUNNER.read_bytes()\n    require(hashlib.sha256(raw).hexdigest()==LEGACY_SHA,'Consumed exact N6 helper source required')\n    module=types.ModuleType('retained_actor_boundary_helpers');module.__file__=str(LEGACY_RUNNER);module.__package__=''\n    exec(compile(raw,str(LEGACY_RUNNER),'exec',dont_inherit=True),module.__dict__)")
 protocol=(F/'actor_context_ranking_resource_protocol_v03.py').read_bytes()
 require(len(protocol)==21090 and hashlib.sha256(protocol).hexdigest()=='5df6178fc35cf2a521501af6ff87b0f629bda92c37226f4534e4946759073c68','Exact current protocol source required')
 runner=raw_loader(runner,"    specification = importlib.util.spec_from_file_location('qualified_actor_context_ranking_resource_guard', protocol_path)\n    protocol = importlib.util.module_from_spec(specification)\n    specification.loader.exec_module(protocol)",
  'protocol_path','protocol','qualified_actor_context_ranking_resource_guard',protocol)
 runner_raw=runner.encode()
 outputs={'run_actor_context_ranking_v04.py':runner_raw}
 for old,new in (
  ('prepare_actor_context_ranking_v03.py','prepare_actor_context_ranking_v04.py'),
  ('actor_context_ranking_bootstrap_smoke_controls_v03.py','actor_context_ranking_bootstrap_smoke_controls_v04.py'),
  ('review_actor_context_ranking_training_plan_v02.py','review_actor_context_ranking_training_plan_v03.py'),
  ('freeze_actor_context_ranking_outputs_v03.py','freeze_actor_context_ranking_outputs_v04.py')):
  source=rebind(retained(old))
  source=once(source,'import os\n','import os\nimport types\n')
  if 'import hashlib\n' not in source:source=once(source,'import types\n','import types\nimport hashlib\n')
  if old.startswith('prepare_'):
   a="spec = importlib.util.spec_from_file_location('actor_context_ranking_metadata_runner', F / 'run_actor_context_ranking_v04.py')\nr = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(r)"
   source=raw_loader(source,a,"F/'run_actor_context_ranking_v04.py'",'r','actor_context_ranking_metadata_runner',runner_raw)
  elif old.startswith('actor_context_ranking_bootstrap'):
   a="    spec = importlib.util.spec_from_file_location('actor_bootstrap_smoke_runner', RUNNER)\n    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)"
   source=raw_loader(source,a,'RUNNER','runner','actor_bootstrap_smoke_runner',runner_raw)
  elif old.startswith('review_'):
   a="    specification = importlib.util.spec_from_file_location('qualified_actor_plan_runner', F / 'run_actor_context_ranking_v04.py')\n    r = importlib.util.module_from_spec(specification)\n    specification.loader.exec_module(r)"
   source=raw_loader(source,a,"F/'run_actor_context_ranking_v04.py'",'r','qualified_actor_plan_runner',runner_raw)
  else:
   a="spec = importlib.util.spec_from_file_location('actor_metadata_runner', F / 'run_actor_context_ranking_v04.py')\nr = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)"
   source=raw_loader(source,a,"F/'run_actor_context_ranking_v04.py'",'r','actor_metadata_runner',runner_raw)
  outputs[new]=source.encode()
 terminal=rebind(retained('audit_actor_context_ranking_terminal_resources_v03.py'))
 terminal=once(terminal,'import stat\n','import stat\nimport types\nimport hashlib\n')
 a="spec=importlib.util.spec_from_file_location('actor_context_ranking_terminal_protocol',F/'actor_context_ranking_resource_protocol_v03.py')\np=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)"
 terminal=raw_loader(terminal,a,"F/'actor_context_ranking_resource_protocol_v03.py'",'p','actor_context_ranking_terminal_protocol',protocol)
 outputs['audit_actor_context_ranking_terminal_resources_v04.py']=terminal.encode()
 for name,raw in outputs.items():
  ast.parse(raw,filename=name);require(not (F/name).exists(),'Never overwrite a draft: '+name)
 for name,raw in outputs.items():
  path=F/name
  with path.open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  path.chmod(0o444)
  print(name,len(raw),hashlib.sha256(raw).hexdigest())


if __name__=='__main__':main()
