"""Versioned CP128 warm start with matched fresh-Adam objective branches.

This profile retains the exact original role checkpoint as immutable provenance.
Both branches inherit its thirteen tensors, rows, codec and semantic-priority
weights; only vocabulary normalization differs. New progress and named Adam
state belong to this successor. These authored384 fixtures confer no legal,
source-encoder, gold, graph, Lean or native execution authority.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import stat

SCHEMA = 'legal-compact-role-warmstart-training-checkpoint/v1'
PROFILE = 'authored-h0-384-fixed537-CP128-fresh-Adam-role-objective/v1'
POLICY_SCHEMA = 'legal-compact-role-warmstart-objective/v1'
OBSERVATION_SCHEMA = 'legal-compact-role-warmstart-objective-observation/v1'
ARCHITECTURE = 'inherited-joint-gru-h0-only/v1'
PARENT_CHECKPOINT_SHA256 = '2c6b5201e1223c3c25adc07b11062180fbaf5f46ce3c078c5b96395f8d87225a'
PARENT_POLICY_SHA256 = '578562275ac7497b52e564028f4dae560b444aca5d0e59275683f5134dfc51ed'
PARENT_WEIGHTS_SHA256 = 'd4e7c710a8aba4462aab575d9bbfb4278c1870fadaf304f80d0f341af4912c34'
PARENT_ADAM_SHA256 = '332e7bff0732b5eb15e5339813aa9455533fd711da87d5e76706f9e07f20d746'
HISTORICAL_PARENT_PROGRESS = dict(optimizer_steps=128, epochs_completed=64, row_cursor=0)
MAX_CHECKPOINT_BYTES = 4 * 1024**2
MAX_INPUT_BYTES = 24 * 1024**2
AUTHORITY = {name:False for name in ('source_encoder_authenticated','source_semantics_verified',
    'training_gold_qualified','heldout_accuracy','statutory_accuracy','production_ready',
    'graph_admission','Lean_admission','native_admission')}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SPECS = (
    ('role_training','logic/formalization/autoencoder/legal_compact_content_role_training_v1.py',
     '7d1562aa7109dc9998fcf533357262a352e9a8c72425bf5d4c02537a9e0d685c'),
)
_MECHANICS = ('config','codec','codec_sha256','runtime','runtime_sha256','parameter_order',
              'optimizer_config','adam_policy','update_policy')
_FIELDS = {'schema','profile','architecture','input_dimension','vocabulary_size','max_total_ids',
    'warmstart_parent_checkpoint','warmstart_parent_checkpoint_sha256','warmstart_parent_policy_sha256',
    'historical_parent_progress','historical_parent_optimizer_state_sha256',
    'basis_checkpoint_sha256','basis_policy_sha256','role_inventories_sha256',
    'config','codec','codec_sha256','runtime','runtime_sha256','parameter_order',
    'optimizer_config','adam_policy','update_policy','optimizer_history_origin',
    'objective_policy','objective_policy_sha256','model_state','weights_sha256',
    'initial_weights_sha256','optimizer_state','optimizer_state_sha256','progress',
    'initial_checkpoint_sha256','parent_checkpoint_sha256','implementation',
    'authority','training_mask','evaluation_gold_mask'}


class RoleWarmstartTrainingError(ValueError):
    """A closed parent, objective, state, source or successor lineage check failed."""


def _need(value, message):
    if not value:
        raise RoleWarmstartTrainingError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, 'independent SHA256 required: '+label)


def _wire(value):
    try:
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    except (TypeError,ValueError,UnicodeError,RecursionError,OverflowError) as error:
        raise RoleWarmstartTrainingError('bounded ordinary finite JSON required') from error
    _need(len(raw)<=MAX_INPUT_BYTES,'whole canonical JSON byte bound exceeded')
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True)==path,'unaliased canonical source required')
    before=path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=131072,
          'bounded single-link owner source required')
    body=path.read_bytes();after=path.lstat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
    _need(identity(before)==identity(after) and len(body)==before.st_size
          and hashlib.sha256(body).hexdigest()==expected,'owner source bytes or identity changed')
    return dict(path=str(path),bytes=len(body),sha256=expected),identity(after)


def _owners():
    root=None
    for ancestor in _SELF_PATH.parents:
        for candidate in (ancestor/'ipfs_datasets_py',ancestor/'external/ipfs_datasets/ipfs_datasets_py'):
            if (candidate/_SPECS[0][1]).is_file():
                root=candidate;break
        if root is not None:break
    _need(root is not None,'canonical warm-start owners unavailable')
    owners,observed={},{}
    for key,relative,pin in _SPECS:
        path=root/relative;seen=_source(path,pin)
        module=importlib.import_module('ipfs_datasets_py.'+relative[:-3].replace('/','.'))
        _need(type(module.__file__) is str and Path(module.__file__).absolute()==path
              and _source(path,pin)==seen,'canonical warm-start owner origin changed')
        owners[key],observed[key]=module,seen
    return root,owners,observed


@contextmanager
def _scope(original):
    root,owners,observed=_owners();own=_source(_SELF_PATH,_SELF_SHA);failure=None
    def outer():
        _need(_source(_SELF_PATH,_SELF_SHA)==own,'warm-start source changed')
        for key,relative,pin in _SPECS:
            _need(_source(root/relative,pin)==observed[key]
                  and type(owners[key].__file__) is str
                  and Path(owners[key].__file__).absolute()==root/relative,
                  'warm-start dependency custody changed')
    try:
        with owners['role_training']._scope(original) as (data,modules,input_fence):
            modules.update(owners)
            def fence():
                input_fence();outer()
            fence();yield data,modules,fence;fence()
    except BaseException as error:
        failure=error
        if isinstance(error,ValueError) and not isinstance(error,RoleWarmstartTrainingError):
            failure=RoleWarmstartTrainingError(str(error));raise failure from error
        raise
    finally:
        try:outer()
        except BaseException:
            if failure is None:raise
            BaseException.add_note(failure,'A closing warm-start custody check also failed.')


def _implementation():
    return dict(role_warmstart_training_sha256=_SELF_SHA,
                direct_owners={relative:pin for _,relative,pin in _SPECS})


def _policy(objective_kind, modules):
    _need(type(objective_kind) is str and objective_kind in ('full537','scope_conditional'),
          'closed full537 or scope_conditional objective required')
    inherited=modules['role_policy'].policy('semantic_priority')
    _need(_digest(inherited)==PARENT_POLICY_SHA256,
          'original semantic-priority role policy differs')
    return dict(schema=POLICY_SCHEMA,objective_kind=objective_kind,weighting='semantic_priority',
        inherited_role_policy_sha256=PARENT_POLICY_SHA256,
        vocabulary_normalization='all537' if objective_kind=='full537' else 'original_scope_allowed_ids',
        normalization='sum_of_complete_position_weights',
        complete_weight_sum=dict(numerator=67,denominator=1),required_supervised_positions=46,
        required_singleton_positions=39,required_nontrivial_positions=7,
        input_dimension=384,vocabulary_size=537,optimizer_origin='fresh_Adam_for_each_objective',
        parent_optimizer_state_inherited=False,target_exposed=True,
        upstream_semantics_or_grammar_authority=False)


def policy(objective_kind):
    """Return the new objective descriptor, retaining original weight provenance."""
    with _scope(dict(objective_kind=objective_kind)) as (data,modules,_):
        return _policy(data['objective_kind'],modules)


def policy_sha256(value):
    """Validate an exact new objective descriptor before canonical hashing."""
    with _scope(dict(policy=value)) as (data,modules,_):
        offered=data['policy']
        _need(type(offered) is dict and 'objective_kind' in offered,'new objective descriptor required')
        _need(_wire(offered)==_wire(_policy(offered['objective_kind'],modules)),
              'new objective descriptor differs from closed definition')
        return _digest(offered)


def _parent(offered,expected,expected_policy,modules):
    _need(expected==PARENT_CHECKPOINT_SHA256 and expected_policy==PARENT_POLICY_SHA256,
          'exact independently bound retained CP128 parent required')
    parent=modules['role_training']._validate(offered,expected,expected_policy,modules)
    _need(parent['weights_sha256']==PARENT_WEIGHTS_SHA256
          and parent['optimizer_state_sha256']==PARENT_ADAM_SHA256
          and parent['progress']==HISTORICAL_PARENT_PROGRESS
          and parent['objective_policy']['weighting']=='semantic_priority'
          and parent['objective_policy']['objective_kind']=='scope_conditional'
          and len(parent['model_state'])==len(parent['parameter_order'])==13,
          'original CP128 weights, Adam, progress or role policy differ')
    def coordinates(value):
        return sum(coordinates(child) for child in value) if type(value) is list else 1
    _need(sum(coordinates(tensor) for tensor in parent['model_state'].values())==16101,
          'complete original thirteen-tensor CP128 geometry required')
    return parent


def _fresh_adam():
    return dict(schema='adam-default-betas-eps/v1',parameters={})


def _initial(value,parent):
    initial=deepcopy(value)
    initial.update(model_state=deepcopy(parent['model_state']),weights_sha256=parent['weights_sha256'],
        optimizer_state=_fresh_adam(),optimizer_state_sha256=_digest(_fresh_adam()),
        progress=dict(optimizer_steps=0,epochs_completed=0,row_cursor=0),
        initial_checkpoint_sha256=None,parent_checkpoint_sha256=None)
    return initial


def _validate(offered,expected,expected_policy,modules):
    _sha(expected,'checkpoint');_sha(expected_policy,'warm-start objective policy')
    value=modules['runtime']._copy(offered,MAX_CHECKPOINT_BYTES)
    _need(type(value) is dict and set(value)==_FIELDS and _digest(value)==expected,
          'closed independently bound warm-start checkpoint required')
    _need(value['schema']==SCHEMA and value['profile']==PROFILE and value['architecture']==ARCHITECTURE
          and all(type(value[k]) is int and value[k]==n for k,n in
                  [('input_dimension',384),('vocabulary_size',537),('max_total_ids',512)]),
          'warm-start checkpoint geometry differs')
    parent=_parent(value['warmstart_parent_checkpoint'],value['warmstart_parent_checkpoint_sha256'],
                   value['warmstart_parent_policy_sha256'],modules)
    _need(type(value['objective_policy']) is dict and 'objective_kind' in value['objective_policy'],
          'explicit versioned warm-start objective required')
    objective=_policy(value['objective_policy']['objective_kind'],modules)
    _need(_wire(value['objective_policy'])==_wire(objective)
          and value['objective_policy_sha256']==expected_policy==_digest(objective),
          'warm-start objective or independent policy changed')
    for key in _MECHANICS+('basis_checkpoint_sha256','basis_policy_sha256','role_inventories_sha256'):
        _need(_wire(value[key])==_wire(parent[key]),'unchanged inherited field differs: '+key)
    _need(_wire(value['historical_parent_progress'])==_wire(HISTORICAL_PARENT_PROGRESS)
          and value['historical_parent_optimizer_state_sha256']==PARENT_ADAM_SHA256
          and value['initial_weights_sha256']==PARENT_WEIGHTS_SHA256
          and value['optimizer_history_origin']=='fresh_from_immutable_CP128_for_explicit_warmstart_objective'
          and _wire(value['implementation'])==_wire(_implementation()),
          'warm-start history, initial weights or implementation differs')
    modules['head']._state(value['model_state'],value['config'])
    _need(value['weights_sha256']==_digest(value['model_state']),'complete model state identity differs')
    steps=modules['weighted']._progress(value['progress'])
    modules['trainer']._optimizer_state(value['optimizer_state'],value['progress'],value['config'],modules['head'])
    _need(value['optimizer_state_sha256']==_digest(value['optimizer_state']),
          'complete named successor Adam identity differs')
    if not steps:
        _need(value['model_state']==parent['model_state'] and value['optimizer_state']==_fresh_adam()
              and value['initial_checkpoint_sha256'] is None and value['parent_checkpoint_sha256'] is None,
              'new objective must inherit exact CP128 weights with fresh Adam and zero new progress')
    else:
        _sha(value['initial_checkpoint_sha256'],'initial warm-start checkpoint')
        _sha(value['parent_checkpoint_sha256'],'immediate warm-start parent')
        _need(value['initial_checkpoint_sha256']==_digest(_initial(value,parent)),
              'initial warm-start checkpoint lineage differs')
        if steps==1:
            _need(value['parent_checkpoint_sha256']==value['initial_checkpoint_sha256'],
                  'first warm-start update parent differs')
    _need(_wire(value['authority'])==_wire(AUTHORITY)
          and type(value['training_mask']) is type(value['evaluation_gold_mask']) is int
          and value['training_mask']==value['evaluation_gold_mask']==0,
          'warm-start checkpoint grants no semantic eligibility')
    return value


def create(cp128, *, expected_parent_checkpoint_sha256, expected_parent_policy_sha256, objective_kind):
    """Purely fork exact CP128 weights, preserving historical Adam without using it."""
    with _scope(dict(parent=cp128,expected=expected_parent_checkpoint_sha256,
                     expected_policy=expected_parent_policy_sha256,objective_kind=objective_kind)) as (data,modules,_):
        parent=_parent(data['parent'],data['expected'],data['expected_policy'],modules)
        objective=_policy(data['objective_kind'],modules)
        value=dict(schema=SCHEMA,profile=PROFILE,architecture=ARCHITECTURE,input_dimension=384,
            vocabulary_size=537,max_total_ids=512,warmstart_parent_checkpoint=parent,
            warmstart_parent_checkpoint_sha256=data['expected'],warmstart_parent_policy_sha256=data['expected_policy'],
            historical_parent_progress=deepcopy(parent['progress']),
            historical_parent_optimizer_state_sha256=parent['optimizer_state_sha256'],
            objective_policy=objective,objective_policy_sha256=_digest(objective),
            optimizer_history_origin='fresh_from_immutable_CP128_for_explicit_warmstart_objective',
            initial_weights_sha256=parent['weights_sha256'],progress=dict(optimizer_steps=0,epochs_completed=0,row_cursor=0),
            initial_checkpoint_sha256=None,parent_checkpoint_sha256=None,implementation=_implementation(),
            authority=dict(AUTHORITY),training_mask=0,evaluation_gold_mask=0,
            optimizer_state=_fresh_adam(),optimizer_state_sha256=_digest(_fresh_adam()))
        for key in _MECHANICS+('basis_checkpoint_sha256','basis_policy_sha256','role_inventories_sha256',
                              'model_state','weights_sha256'):
            value[key]=deepcopy(parent[key])
        return _validate(value,_digest(value),_digest(objective),modules)


def checkpoint_sha256(checkpoint):
    with _scope(dict(checkpoint=checkpoint)) as (data,modules,_):
        return _digest(modules['runtime']._copy(data['checkpoint'],MAX_CHECKPOINT_BYTES))


def inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Validate full plain state without constructing a model or optimizer."""
    with _scope(dict(checkpoint=checkpoint,expected=expected_checkpoint_sha256,expected_policy=expected_policy_sha256)) as (data,modules,_):
        value=_validate(data['checkpoint'],data['expected'],data['expected_policy'],modules)
        return dict(schema=SCHEMA,profile=PROFILE,checkpoint_sha256=data['expected'],
            objective_policy_sha256=data['expected_policy'],weighting='semantic_priority',
            objective_kind=value['objective_policy']['objective_kind'],
            warmstart_parent_checkpoint_sha256=value['warmstart_parent_checkpoint_sha256'],
            warmstart_parent_policy_sha256=value['warmstart_parent_policy_sha256'],
            historical_parent_progress=deepcopy(value['historical_parent_progress']),
            historical_parent_optimizer_state_sha256=value['historical_parent_optimizer_state_sha256'],
            basis_checkpoint_sha256=value['basis_checkpoint_sha256'],role_inventories_sha256=value['role_inventories_sha256'],
            weights_sha256=value['weights_sha256'],optimizer_state_sha256=value['optimizer_state_sha256'],
            progress=deepcopy(value['progress']),parameter_order=list(value['parameter_order']),
            inherited_model_tensors=13,inherited_coordinates=16101,parent_Adam_inherited=False,
            model_constructed=False,optimizer_constructed=False,runtime_verified=False,checkpoint_schema_conversion=False,
            later_parent_is_commitment_not_replayed=value['progress']['optimizer_steps']>1,authority=dict(AUTHORITY))


def _row(value, modules):
    index=value['progress']['row_cursor'];parent=value['warmstart_parent_checkpoint'];basis=parent['basis_checkpoint']
    stored=basis['rows_utf8'][index];inventory=parent['role_inventories'][index]
    return dict(id=stored['id'],row_index=index,conditioning=deepcopy(stored['conditioning']),
        target_ids=list(inventory['target_ids']),position_weights=list(inventory['position_weights']),
        inventory_sha256=inventory['baseline_inventory_sha256'],
        baseline_inventory_sha256=inventory['baseline_inventory_sha256'],
        scope_inventory_sha256=inventory['scope_inventory_sha256'],role_inventory_sha256=_digest(inventory),
        policy_sha256=value['objective_policy_sha256'],objective_kind=value['objective_policy']['objective_kind'],
        weighting=value['objective_policy']['weighting'],scope_policy_sha256=basis['scope_policy_sha256'],
        scope_allowed_token_ids=deepcopy(inventory['scope_allowed_token_ids']),
        baseline_decision_kinds=[p['decision_kind'] for p in basis['inventories'][index]['positions']],
        position_roles=[p['role'] for p in inventory['positions']],
        position_syntax_roles=[p['syntax_role'] for p in inventory['positions']],
        role_positions=deepcopy(inventory['positions']),singleton_positions=39,nontrivial_positions=7)


def training_row(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    with _scope(dict(checkpoint=checkpoint,expected=expected_checkpoint_sha256,expected_policy=expected_policy_sha256)) as (data,modules,_):
        return _row(_validate(data['checkpoint'],data['expected'],data['expected_policy'],modules),modules)


def restore(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Restore actual warm-start tensors and named Adam through original owners."""
    with _scope(dict(checkpoint=checkpoint,expected=expected_checkpoint_sha256,expected_policy=expected_policy_sha256)) as (data,modules,fence):
        value=_validate(data['checkpoint'],data['expected'],data['expected_policy'],modules)
        weighted=modules['weighted'];numerical,torch,runtime=weighted._numeric(modules)
        _need(_wire(runtime)==_wire(value['runtime']),'actual restoration runtime differs')
        rng=torch.get_rng_state().clone()
        try:
            model=numerical._model({'dimension':384},{'target_vocabulary':value['codec']['vocabulary']},value['config'])
            templates=model.state_dict();_need(list(templates)==value['parameter_order'],'restored parameter order differs')
            model.load_state_dict({name:numerical._tensor(value['model_state'][name],template,name)
                                   for name,template in templates.items()},strict=True);model.eval()
            optimizer=numerical._optimizer(model,value['optimizer_config'])
            for name,parameter in model.named_parameters():
                stored=value['optimizer_state']['parameters'].get(name)
                if stored is not None:
                    optimizer.state[parameter]={'step':torch.tensor(float(stored['step']),dtype=torch.float32,device='cpu'),
                        'exp_avg':numerical._tensor(stored['exp_avg'],parameter,name+'.exp_avg'),
                        'exp_avg_sq':numerical._tensor(stored['exp_avg_sq'],parameter,name+'.exp_avg_sq',nonnegative=True)}
            weights,moments=weighted._actual(model,optimizer,value,value['progress']['optimizer_steps'],modules,numerical,torch)
            _need(weights==value['model_state'] and moments==value['optimizer_state'],'exact named warm-start restore differs')
            return model,optimizer
        finally:
            fence()
            _need(torch.equal(rng,torch.get_rng_state()) and _wire(weighted._numeric(modules)[2])==_wire(runtime),
                  'restoration changed CPU RNG or numerical runtime')


def objective(checkpoint, logits, *, expected_checkpoint_sha256, expected_policy_sha256):
    """One new role-weighted scalar; no model, backward or update."""
    with _scope(dict(checkpoint=checkpoint,expected=expected_checkpoint_sha256,expected_policy=expected_policy_sha256)) as (data,modules,fence):
        value=_validate(data['checkpoint'],data['expected'],data['expected_policy'],modules);row=_row(value,modules)
        weighted=modules['weighted'];_,torch,runtime=weighted._numeric(modules)
        _need(_wire(runtime)==_wire(value['runtime']),'actual objective runtime differs')
        _need(isinstance(logits,torch.Tensor) and logits.device.type=='cpu' and logits.dtype is torch.float32
              and tuple(logits.shape)==(1,46,537) and logits.requires_grad and bool(torch.isfinite(logits).all()),
              'complete differentiable finite teacher-forced scores required before masking')
        version,saved,rng=logits._version,logits.detach().clone(),torch.get_rng_state().clone()
        try:
            labels=torch.tensor(row['target_ids'][1:],dtype=torch.long,device='cpu')
            weights=torch.tensor(row['position_weights'],dtype=torch.float32,device='cpu')
            _need(bool((labels!=0).all()) and float(weights.sum())==67.0,'complete no-padding role weights sum67 required')
            flat=logits.reshape(-1,537);allowed=torch.zeros_like(flat,dtype=torch.bool)
            for i,choices in enumerate(row['scope_allowed_token_ids']):
                _need(choices and row['target_ids'][i+1] in choices,'original target absent from scope mask')
                allowed[i,choices]=True
            conditional=value['objective_policy']['objective_kind']=='scope_conditional'
            if conditional:
                losses=torch.nn.functional.cross_entropy(flat.masked_fill(~allowed,-torch.inf),labels,ignore_index=0,reduction='none')
                with torch.no_grad():full=torch.nn.functional.cross_entropy(flat,labels,ignore_index=0,reduction='none')
            else:
                # Original scope-training full537 CE primitive, with its gradient intact.
                losses=torch.nn.functional.cross_entropy(flat,labels,ignore_index=0,reduction='none')
                full=losses
            loss=(losses*weights).sum()/weights.sum()
            _need(loss.ndim==0 and loss.requires_grad and bool(torch.isfinite(loss))
                  and bool(torch.isfinite(losses).all()) and bool(torch.isfinite(full).all()),'finite warm-start role objective required')
            report=dict(schema=OBSERVATION_SCHEMA,checkpoint_sha256=data['expected'],
                objective_policy_sha256=data['expected_policy'],objective_kind=value['objective_policy']['objective_kind'],weighting=value['objective_policy']['weighting'],
                warmstart_parent_checkpoint_sha256=value['warmstart_parent_checkpoint_sha256'],
                historical_parent_progress=deepcopy(value['historical_parent_progress']),
                parent_Adam_inherited=False,basis_checkpoint_sha256=value['basis_checkpoint_sha256'],row_id=row['id'],row_index=row['row_index'],
                inventory_sha256=row['inventory_sha256'],baseline_inventory_sha256=row['baseline_inventory_sha256'],
                scope_inventory_sha256=row['scope_inventory_sha256'],role_inventory_sha256=row['role_inventory_sha256'],
                scope_policy_sha256=row['scope_policy_sha256'],target_ids=row['target_ids'],label_ids=row['target_ids'][1:],
                position_weights=row['position_weights'],position_roles=row['position_roles'],
                position_syntax_roles=row['position_syntax_roles'],weight_sum=67.0,
                supervised_positions=46,scope_allowed_token_ids=row['scope_allowed_token_ids'],
                baseline_decision_kinds=row['baseline_decision_kinds'],singleton_positions=39,nontrivial_positions=7,
                per_position_losses=losses.detach().tolist(),weighted_loss=float(loss.detach()),
                full537_per_position_losses=full.detach().tolist(),
                full537_weighted_loss=float(((full*weights).sum()/weights.sum()).detach()),
                reduction='scope_masked_none_role_weighted_sum_divide67' if conditional else 'full537_none_role_weighted_sum_divide67',full537_logits_observed=True,
                full537_vocabulary=not conditional,conditional_allowed_set_loss=conditional,singleton_zero_loss_is_not_accuracy=True,
                full537_and_conditional_losses_not_comparable_as_accuracy=True,teacher_forcing=True,
                forward_performed=False,backward_performed=False,optimizer_update_performed=False,
                structural_role_priority_is_not_semantic_verification=True,authority=dict(AUTHORITY))
            return loss,report
        finally:
            fence()
            _need(logits._version==version and torch.equal(saved,logits.detach()) and torch.equal(rng,torch.get_rng_state())
                  and _wire(weighted._numeric(modules)[2])==_wire(runtime),'objective mutated input/RNG or runtime')


def pack(model, optimizer, checkpoint, progress, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Commit exactly one actual named update under the new warm-start objective."""
    with _scope(dict(checkpoint=checkpoint,progress=progress,expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data,modules,fence):
        value=_validate(data['checkpoint'],data['expected'],data['expected_policy'],modules)
        weighted=modules['weighted'];steps=weighted._progress(data['progress'])
        _need(steps==value['progress']['optimizer_steps']+1,'warm-start packing must advance exactly one actual update')
        numerical,torch,runtime=weighted._numeric(modules);_need(_wire(runtime)==_wire(value['runtime']),'actual packing runtime differs')
        rng=torch.get_rng_state().clone()
        try:
            weights,moments=weighted._actual(model,optimizer,value,steps,modules,numerical,torch)
            result=deepcopy(value)
            result.update(model_state=weights,weights_sha256=_digest(weights),optimizer_state=moments,
                optimizer_state_sha256=_digest(moments),progress=deepcopy(data['progress']),parent_checkpoint_sha256=data['expected'],
                initial_checkpoint_sha256=data['expected'] if value['progress']['optimizer_steps']==0 else value['initial_checkpoint_sha256'])
            return _validate(result,_digest(result),data['expected_policy'],modules)
        finally:
            fence()
            _need(torch.equal(rng,torch.get_rng_state()) and _wire(weighted._numeric(modules)[2])==_wire(runtime),
                  'packing changed CPU RNG or numerical runtime')


__all__=['RoleWarmstartTrainingError','create','policy','policy_sha256','checkpoint_sha256','inspect','training_row','restore','objective','pack']
