"""Actual bounded Source384 context on the complete permitted public population."""
from pathlib import Path
import hashlib,json,sys,time,traceback
ROOT=Path('/home/barberb/lift_coding')
sys.path[:0]=[str(ROOT/'.worktrees/ir-release-accelerate-20261002'),str(ROOT/'.worktrees/ir-release-datasets-20261002')]
from ipfs_accelerate_py.agent_supervisor.runtime import source384_repository_context as owner
from ipfs_datasets_py.logic.software_contracts import codebase_ir
BASE=ROOT/'artifacts/source-combined-observation-performance-20261003'
retained=json.loads((BASE/'after-02/receipt.json').read_text())
repository=BASE/'after-02/app'
out=BASE/sys.argv[1];out.mkdir()
config=ROOT/'artifacts/terminal-source384-context-20261003/bottle-canary-02/source384-config.json'
record=dict(schema='full-public-source384-native-context@1',script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),source_files=retained['source_files'],source_hashes=retained['source_hashes'],repository=str(repository),producer_before=owner._pins(),deadline_seconds=90,provider_calls=0,training_steps=0,benchmark_result=False,source_population='original218-plus-native-instruction-and-public-smoke',fresh_state=True)
begun=time.monotonic()
try:
 receipt=owner.prepare_source384_context(repository=repository,source_hashes=retained['source_hashes'],output=out/'state',config_path=config,timeout_seconds=90)
 inference=json.loads((out/'state/inference.json').read_bytes())
 record.update(status='passed',receipt=receipt,coverage=inference['report']['coverage'],native_worker_executed=inference['native_worker_executed'],inference_executed=inference['inference_executed'],model_loads=inference['report']['output']['model_loads'])
except Exception as exc:
 record.update(status='failed',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
finally:
 record.update(seconds=time.monotonic()-begun,producer_after=owner._pins(),manifest_memo=dict(codebase_ir._MANIFEST_MEMO_STATS,entries=len(codebase_ir._MANIFEST_MEMO),retained_bytes=codebase_ir._MANIFEST_MEMO_SIZE,limit_bytes=codebase_ir._MANIFEST_MEMO_BYTES))
 (out/'receipt.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
 print(json.dumps({k:v for k,v in record.items() if k not in ('receipt','source_hashes','producer_before','producer_after')},sort_keys=True))

