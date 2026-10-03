"""Explicit same-ledger scheduler selection for this qualification process only."""
from pathlib import Path
import hashlib,json,os,time
import pytest

B=Path(__file__).resolve().parent
STATE=Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')

def observe_state():
    with STATE.open('rb') as f:raw=f.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('shared scheduler state exceeds diagnostic bound')
    value=json.loads(raw)
    def public_records(name):
        return [{k:r.get(k) for k in ('owner_pid','request_id','cpu_slots','memory_mb','lane')}
                for r in value.get(name,{}).values()]
    return dict(timestamp=time.time(),state_path=str(STATE),state_sha256=hashlib.sha256(raw).hexdigest(),
        config=value['config'],leases=public_records('leases'),waiters=public_records('waiters'),
        proof_recovery_present=bool(value.get('proof_recovery')))

class ExplicitClientPlugin:
    @pytest.fixture(scope='session',autouse=True)
    def declared_shared_scheduler(self):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            ResourceSchedulerConfig,get_global_resource_scheduler,collect_proof_host_resources)
        from ipfs_datasets_py.logic.software_contracts import codebase_resources
        before=observe_state()
        cfg=ResourceSchedulerConfig(**before['config'],state_path=STATE)
        cfg.validate()
        assert cfg.proof_resource_sampler is collect_proof_host_resources
        assert cfg.proof_safety_enabled and cfg.state_path==STATE
        scheduler=get_global_resource_scheduler(cfg)
        selected=dict(mode='explicit_configured_client_same_native_ledger',
            dependency='codebase_resources.get_global_resource_scheduler',
            canonical_api='get_global_resource_scheduler(existing_config)',
            before=before,selected_config=cfg.persisted_dict(),native_sampler=True,
            thresholds_changed=False,new_ledger=False,daemon_modified=False,host_default_qualification=False)
        (B/'native-03-configured-client-before.json').write_text(json.dumps(selected,indent=2)+'\n')
        original=codebase_resources.get_global_resource_scheduler
        def selected_owner():return get_global_resource_scheduler(cfg)
        codebase_resources.get_global_resource_scheduler=selected_owner
        try:yield scheduler
        finally:
            codebase_resources.get_global_resource_scheduler=original
            after=observe_state()
            (B/'native-03-configured-client-after.json').write_text(json.dumps(dict(after=after,
                dependency_restored=codebase_resources.get_global_resource_scheduler is original,
                selected_config=cfg.persisted_dict()),indent=2)+'\n')
