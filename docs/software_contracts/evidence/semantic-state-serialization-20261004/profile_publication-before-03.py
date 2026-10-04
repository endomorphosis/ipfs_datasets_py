"""Single public-source cold publication diagnostic, never native qualification."""
import functools
import cProfile
import pstats
import io
import hashlib
import json
import pathlib
import subprocess
import sys
import time

import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
from ipfs_datasets_py.duckdb_control import codebase_catalog as catalog_module
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseScanLimits, RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig

B = pathlib.Path(__file__).resolve().parent
D = pathlib.Path(sys.modules[CodebaseCatalog.__module__].__file__).resolve().parents[2]
label = sys.argv[1]
private = B / "private" / label
private.mkdir(parents=True, exist_ok=False)
repository = private / "repository"
repository.mkdir()
source = pathlib.Path('/home/barberb/lift_coding/.worktrees/ir-release-accelerate-20261002/docs/agent_supervisor/evidence/pressure-replay-components-20261004/reconstruction/inputs/bottle.py')
raw = source.read_bytes()
assert len(raw) == 175565
assert hashlib.sha256(raw).hexdigest() == '761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba'
(repository / 'bottle.py').write_bytes(raw)
for arguments in [('init', '-q'), ('config', 'user.name', 'Public fixture'), ('config', 'user.email', 'fixture@example.invalid'), ('add', '.'), ('commit', '-qm', 'public fixture')]:
    subprocess.run(['git', '-C', str(repository), *arguments], check=True, capture_output=True)
pin_paths = json.loads((B / 'before-source-pins.json').read_text())['source_sha256']
def pins():
    return {path: hashlib.sha256((D / path).read_bytes()).hexdigest() for path in pin_paths}
record = dict(diagnostic_only=True, scope='Single public Bottle cold index publication; isolated native file-backed stores and synthetic resource admission; no model, Docker or verifier', source_bytes=len(raw), source_sha256=hashlib.sha256(raw).hexdigest(), source_pins_before=pins(), events=[])
owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(state_path=private / 'scheduler.json', proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192), lane_reservations={}, auto_renew_leases=False))
connection = duckdb.connect(str(private / 'index.duckdb'), config={'threads': 1, 'memory_limit': '256MB'})
store = DuckDBASTStore(connection=connection)
cas = ImmutableCAS(private / 'cas')
catalog = CodebaseCatalog(store, cas)
index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas, catalog=catalog)
originals = []
def wrap(cls, name):
    original = vars(cls)[name]
    function = original.__func__ if isinstance(original, classmethod) else original
    @functools.wraps(function)
    def measured(*args, **kwargs):
        caller = sys._getframe(1).f_code.co_name
        cpu, wall = time.process_time(), time.monotonic()
        outcome = 'returned'
        profiler = cProfile.Profile() if name == '_reconstruct_manifest' else None
        if profiler is not None: profiler.enable()
        try:
            return function(*args, **kwargs)
        except BaseException:
            outcome = 'raised'
            raise
        finally:
            if profiler is not None:
                profiler.disable()
                profiler.dump_stats(str(B / (label + '-manifest.prof')))
                stream = io.StringIO()
                pstats.Stats(profiler, stream=stream).sort_stats('cumulative').print_stats(65)
                (B / (label + '-manifest-profile.txt')).write_text(stream.getvalue())
            record['events'].append(dict(stage=cls.__name__ + '.' + name, caller=caller, status=outcome, cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-wall))
    originals.append((cls, name, original))
    setattr(cls, name, classmethod(measured) if isinstance(original, classmethod) else measured)
for cls, name in [(catalog_module, '_reconstruct_manifest'), (catalog_module, '_manifest_native_equal'), (ASTRecord, 'from_dict'), (CodebaseCatalog, '_read_artifact'), (CodebaseCatalog, '_validate_candidate'), (DuckDBASTStore, '_validate_projection'), (DuckDBASTStore, 'apply_batch'), (DuckDBASTStore, '_persist_projection')]:
    wrap(cls, name)
cpu, wall = time.process_time(), time.monotonic()
try:
    receipt = index.prepare_current(repository, repository_id='repository:public-bottle-cold', operation_id='initial', expected_head=None, scheduler=owner, limits=CodebaseScanLimits(max_entries=4, max_file_bytes=256*1024), timeout_seconds=90)
    record.update(status='returned', cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-wall, manifest_cid=receipt.manifest_cid, snapshot_cid=receipt.snapshot_cid)
    record['ast_payload_bytes'] = [row[0] for row in connection.execute('SELECT octet_length(encode(payload_json)) FROM ast_blobs').fetchall()]
    state = owner.snapshot()
    record['leases_after'] = dict(active=state['active_lease_count'], waiting=state['waiting_request_count'])
    assert record['leases_after'] == dict(active=0, waiting=0)
except BaseException as error:
    record.update(status='raised', error_type=type(error).__name__, cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-wall)
    raise
finally:
    for cls, name, original in reversed(originals):
        setattr(cls, name, original)
    connection.close()
    record['source_pins_after'] = pins()
    record['source_pins_unchanged'] = record['source_pins_before'] == record['source_pins_after']
    (B / (label + '-result.json')).write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
