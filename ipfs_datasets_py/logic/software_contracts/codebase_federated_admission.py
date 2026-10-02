"""Independent 8D reconstruction retention and native model-head CAS.

This gate replays exact current source, completed local work, binary reduction
and immutable parent/root canaries. It grants model selection only; numerical
feature reconstruction is not semantic or property proof. Registry/source
owners remain separate, and federation candidates are never auto-promoted.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from . import codebase_federated_training as federation
from . import codebase_source_training as source

PROTOCOL = 'codebase-federated-fixed-feature-retention@1'


def _score(saved, targets):
    runtime=federation._runtime(saved)
    inference=runtime.infer(targets)
    vectors,ids,_=features._matrix(runtime.feature_space,targets)
    source._require([row['source_digest'] for row in inference['rows']]==ids,'retention source population differs')
    losses=[]
    for target,row in zip(vectors,inference['rows']):
        decoded=[n for name in runtime.feature_space['projection_ids'] for n in row['reconstructed_projection_features'][name]]
        source._require(len(decoded)==len(target),'retention feature layout differs')
        losses.append(sum((a-b)**2 for a,b in zip(target,decoded))/len(target))
    return dict(source_digests=ids,mean_squared_errors=losses,mean_squared_error=sum(losses)/len(losses))


def evaluate_retention(index,registry,version_id):
    """Independently reevaluate fixed development canaries; no fitting/writes."""
    limits=source.CodebaseFeatureTrainingLimits()
    candidate=federation._parent(index,registry,version_id,limits)
    saved=candidate['saved'];report=saved['report'].get('codebase_federation')
    source._require(report is not None,'completed federated candidate required')
    parent=federation._parent(index,registry,candidate['row']['parent_version_id'],limits)
    origin=federation._parent(index,registry,candidate['origin_version_id'],limits)
    scores={}
    for role in ('canary','replay'):
        targets=parent[role]
        scores[role]={name:_score(value,targets) for name,value in
            (('candidate',saved),('parent',parent['saved']),('origin',origin['saved']))}
    changed=saved['state']['parameters']!=parent['saved']['state']['parameters']
    # Exact float64 implementation and fixed rows are independently replayed.
    # A small documented arithmetic tolerance covers only last-bit summation.
    retained=all(all(new<=old+1e-12 for new,old in zip(scores[role]['candidate']['mean_squared_errors'],
        scores[role][baseline]['mean_squared_errors'])) for role in scores for baseline in ('parent','origin'))
    return dict(protocol_id=PROTOCOL,candidate_version_id=version_id,parent_version_id=candidate['row']['parent_version_id'],
        candidate_artifact=candidate['row']['artifact'],source_head=report['head'],round_sha256=federation._round(report['round']).round_sha256,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scores=scores,nonzero_parameter_change=changed,retained=retained,
        evaluation_role='fixed_development_retention_not_unseen_test',training_executed=False,
        semantic_or_property_proof=False,proof_authority=False)


class RetentionPolicy:
    """Install on the existing native registry before opening any model head."""
    def __init__(self,index):self.index,self.registry=index,None
    def bind(self,registry):
        source._require(type(registry) is AutoencoderRegistry and self.registry is None,'one native registry binding required')
        self.registry=registry
    def __call__(self,version,evaluation):
        try:
            source._require(self.registry is not None,'retention owner is not bound')
            expected=evaluate_retention(self.index,self.registry,version['version_id'])
            source._require(evaluation==expected and expected['retained'] and expected['nonzero_parameter_change'],
                'independent fixed feature retention refused')
            source._require(self.registry.get_version(version['version_id'])==version,'retention native version differs')
            return True
        except (ValueError,KeyError,TypeError):return False


def promote_current(index,repository,*,expected_head,registry,version_id,expected_model_head,operation_id,
        scheduler=None,parent_lease=None,cancel_event=None,timeout_seconds=60.,memory_mb=4096):
    """Check independent retention then advance only the exact declared parent."""
    limits=source.CodebaseFeatureTrainingLimits()
    with source._resources(index,repository,expected_head,scheduler=scheduler,parent_lease=parent_lease,
            cancel_event=cancel_event,admission_timeout_seconds=min(30.,timeout_seconds),
            timeout_seconds=timeout_seconds,memory_mb=memory_mb,limits=limits) as (_,_,remaining,observe):
        row=registry.get_version(version_id)
        source._require(type(expected_model_head) is dict and
            set(expected_model_head)=={'variant_id','branch','version_id','generation'} and
            expected_model_head['variant_id']==row['variant_id'] and
            expected_model_head['version_id']==row['parent_version_id'] and
            registry.resolve_head(row['variant_id'],expected_model_head['branch'])==expected_model_head,
            'exact current federated parent head required')
        evaluation=evaluate_retention(index,registry,version_id)
        source._require(evaluation['source_head']==expected_head.to_dict(),'federated candidate source differs')
        remaining();observe()
        return registry.promote_head(operation_id,row['variant_id'],expected_model_head['branch'],version_id,
            expected_version_id=expected_model_head['version_id'],expected_generation=expected_model_head['generation'],
            evaluation=evaluation)
