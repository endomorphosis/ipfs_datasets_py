import json,pathlib
from ipfs_accelerate_py.agent_supervisor.runtime.repository_resource_bridge import RepositoryResourceBridge,RepositoryResourceBudget,RepositoryPhaseDemand
from ipfs_accelerate_py.agent_supervisor.runtime.resource_scheduler import ResourceScheduler,ResourcePolicy
from ipfs_datasets_py.logic.software_contracts.codebase_family_execution import seal_family_tools,execute_family,MEMORY_MB
from ipfs_datasets_py.logic.software_contracts.codebase_family_lowering import CodebaseFamilyBundle
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import compile_integer_offset,IntegerOffsetContract
root=pathlib.Path('/tmp/codebase-family-isabelle-retry');root.mkdir(exist_ok=True)
toolsroot=pathlib.Path('/home/barberb/.local/share/ipfs_datasets_py/theorem-provers');toolsbin=toolsroot/'bin'
java=toolsroot/'Isabelle2025-2-linux-aarch64/Isabelle2025-2/contrib/jdk-21.0.9/arm64-linux/bin/java'
paths=dict(lean='/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lean',rocq=str(toolsbin/'coqtop'),isabelle=str(toolsbin/'isabelle'),z3='/home/barberb/.local/bin/z3',cvc5='/home/barberb/.local/bin/cvc5',tlc=str(toolsbin/'tlc'),java=str(java))
policy=seal_family_tools(paths,runtime_artifacts={'tlc':[toolsroot/'tlc/1.8.0/tla2tools.jar',java],'rocq':[toolsroot/'opam/ipfs-datasets-coq/bin/rocq'],'isabelle':[toolsroot/'Isabelle2025-2-linux-aarch64/Isabelle2025-2/bin/isabelle']})
c=compile_integer_offset(b'def increment(n: int) -> int:\n    return n + 1\n',IntegerOffsetContract('main.py','increment','n',1),revision='native-smoke')
bundle=CodebaseFamilyBundle(c,(-1,0,1));rows=[]
with RepositoryResourceBridge(ResourceScheduler(ResourcePolicy(max_lanes=8))).reserve(repository_id='codebase-family-native-smoke',workspace=root,budget=RepositoryResourceBudget(cpu_slots=1,memory_mb=2048,process_slots=1,wall_time_ms=240000)) as parent:
 for backend in ['isabelle']:
  with parent.phase(RepositoryPhaseDemand('proof',memory_mb=MEMORY_MB[backend])) as phase:
   opts=phase.native_options();opts.pop('memory_mb');opts['timeout_seconds']=min(60,opts['timeout_seconds'])
   try:result=execute_family(bundle,policy,backend=backend,**opts)
   except Exception as error:
    import traceback
    result=dict(backend=backend,error=repr(error),traceback=traceback.format_exc())
   rows.append(result);(root/(backend+'.json')).write_text(json.dumps(result,indent=2))
   print(backend,result.get('status',result.get('error')),flush=True)
 (root/'resources.json').write_text(json.dumps(parent.receipt(),indent=2))
(root/'bundle.json').write_text(json.dumps(bundle.to_dict(),indent=2));(root/'tools.json').write_text(json.dumps(policy,indent=2))
