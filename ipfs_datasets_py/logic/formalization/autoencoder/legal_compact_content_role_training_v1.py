"""Explicit role-weighted conditional training over an immutable validated basis.

The old zero-step checkpoint remains an intact historical basis. Current
weights, Adam, objective and lineage belong to this new schema exclusively.
Numerical factories/state validators and fast custody retain their old owners.
This direct API does not create a prepared session or authorize inference.
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

SCHEMA = 'legal-compact-role-training-checkpoint/v1'
PROFILE = 'authored-h0-384-fixed537-conditional-role-objective-development/v1'
ARCHITECTURE = 'inherited-joint-gru-h0-only/v1'
BASIS_SHA256 = '682378075115c98cc9afd2bb19a9d9e7eebed4d1ac1212944c6b24411f9ffea4'
BASIS_POLICY_SHA256 = 'd05de03265f32b14233a27414aa791bccd65f130f42617a65d9b98d9c2e22081'
MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_INPUT_BYTES = 24 * 1024**2
AUTHORITY = {name:False for name in ('source_encoder_authenticated','source_semantics_verified',
    'training_gold_qualified','heldout_accuracy','statutory_accuracy','production_ready',
    'graph_admission','Lean_admission','native_admission')}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SPECS = (
    ('custody','logic/formalization/autoencoder/legal_compact_content_scope_prepared_training_v2.py',
     '9e2d70532e4b559d3d6e808658474b7aaff7d851c89733684fb1c4c51e6e8c78'),
    ('scope_training','logic/formalization/autoencoder/legal_compact_content_scope_training_v1.py',
     'fb86141cd0b69fe74e43cc9460d557e890c90c07178bf9e1a62d15098552c208'),
    ('role_policy','logic/formalization/autoencoder/legal_compact_content_role_policy_v1.py',
     'abc011efbbc6460be7a68832698631d8b34708dbb60253fcbd1d5394a45d1c41'),
)
_FIELDS = {'schema','profile','architecture','input_dimension','vocabulary_size','max_total_ids',
    'basis_checkpoint','basis_checkpoint_sha256','basis_policy_sha256','config','codec','codec_sha256',
    'runtime','runtime_sha256','parameter_order','optimizer_config','adam_policy','update_policy',
    'optimizer_history_origin','objective_policy','objective_policy_sha256','role_inventories',
    'role_inventories_sha256','model_state','weights_sha256','initial_weights_sha256','optimizer_state',
    'optimizer_state_sha256','progress','initial_checkpoint_sha256','parent_checkpoint_sha256',
    'implementation','authority','training_mask','evaluation_gold_mask'}


class RoleTrainingError(ValueError):
    """Closed role-objective, basis, source, numerical or lineage check failed."""


def _need(value, message):
    if not value:
        raise RoleTrainingError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, 'independent SHA256 required: '+label)


def _wire(value):
    try:
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    except (TypeError,ValueError,UnicodeError,RecursionError,OverflowError) as error:
        raise RoleTrainingError('bounded ordinary finite JSON required') from error
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
    _need(root is not None,'canonical role-training owners unavailable')
    owners,observed={},{}
    for key,relative,pin in _SPECS:
        path=root/relative;seen=_source(path,pin)
        module=importlib.import_module('ipfs_datasets_py.'+relative[:-3].replace('/','.'))
        _need(type(module.__file__) is str and Path(module.__file__).absolute()==path
              and _source(path,pin)==seen,'canonical role-training owner origin changed')
        owners[key],observed[key]=module,seen
    return root,owners,observed


@contextmanager
def _scope(original):
    root,owners,observed=_owners();own=_source(_SELF_PATH,_SELF_SHA);failure=None
    def outer():
        _need(_source(_SELF_PATH,_SELF_SHA)==own,'role-training source changed')
        for key,relative,pin in _SPECS:
            _need(_source(root/relative,pin)==observed[key]
                  and type(owners[key].__file__) is str
                  and Path(owners[key].__file__).absolute()==root/relative,'role-training dependency custody changed')
    try:
        with owners['custody']._scope(original) as (data,modules,input_fence):
            modules.update(owners)
            def fence():
                input_fence();outer()
            fence();yield data,modules,fence;fence()
    except BaseException as error:
        failure=error
        if isinstance(error,ValueError) and not isinstance(error,RoleTrainingError):
            failure=RoleTrainingError(str(error));raise failure from error
        raise
    finally:
        try:outer()
        except BaseException:
            if failure is None:raise
            BaseException.add_note(failure,'A closing role-training custody check also failed.')


def _implementation():
    return dict(role_training_sha256=_SELF_SHA,direct_owners={relative:pin for _,relative,pin in _SPECS})


def _basis(offered,expected,expected_policy,modules):
    _need(expected==BASIS_SHA256 and expected_policy==BASIS_POLICY_SHA256,
          'exact independently bound qualified zero-step conditional basis required')
    basis,_=modules['scope_training']._validate(offered,expected,expected_policy,modules)
    _need(basis['progress']==dict(optimizer_steps=0,epochs_completed=0,row_cursor=0)
          and basis['objective_policy']['objective_kind']=='scope_conditional'
          and basis['optimizer_state']['parameters']=={},'immutable zero-step fresh-Adam basis required')
    return basis


# Pure policy algebra is separate from original grammar and basis validation.
def _policy(weighting, modules):
    return modules['role_policy'].policy(weighting)


def _inventories(basis, objective, modules):
    result=[modules['role_policy'].prepare_inventory(basis,index,
        expected_basis_checkpoint_sha256=BASIS_SHA256,
        expected_policy_sha256=_digest(objective),policy=objective) for index in range(2)]
    _need(all(len(row['position_weights'])==46 and math.fsum(row['position_weights'])==67.0
              and row['singleton_positions']==39 and row['nontrivial_positions']==7
              and row['weight_sum']==row['baseline_weight_sum']==67.0
              and row['choice_weight_sum']==28.0 for row in result),
          'complete original population and fixed role weight budget required')
    return result


def _validate(offered,expected,expected_policy,modules):
    _sha(expected,'checkpoint');_sha(expected_policy,'role policy')
    value=modules['runtime']._copy(offered,MAX_CHECKPOINT_BYTES)
    _need(type(value) is dict and set(value)==_FIELDS and _digest(value)==expected,
          'closed independently bound role checkpoint required')
    _need(value['schema']==SCHEMA and value['profile']==PROFILE and value['architecture']==ARCHITECTURE
          and all(type(value[k]) is int and value[k]==n for k,n in
                  [('input_dimension',384),('vocabulary_size',537),('max_total_ids',512)]),'role checkpoint geometry differs')
    basis=_basis(value['basis_checkpoint'],value['basis_checkpoint_sha256'],value['basis_policy_sha256'],modules)
    _need(type(value['objective_policy']) is dict and 'weighting' in value['objective_policy'],
          'explicit versioned role objective required')
    objective=_policy(value['objective_policy']['weighting'],modules)
    _need(_wire(value['objective_policy'])==_wire(objective)
          and value['objective_policy_sha256']==expected_policy==_digest(objective),'role objective or independent policy changed')
    inventories=_inventories(basis,objective,modules)
    _need(_wire(value['role_inventories'])==_wire(inventories)
          and value['role_inventories_sha256']==_digest(inventories),'role inventory differs from original public recomputation')
    for key in ('config','codec','codec_sha256','runtime','runtime_sha256','parameter_order',
                'optimizer_config','adam_policy','update_policy'):
        _need(_wire(value[key])==_wire(basis[key]),'unchanged mechanics field differs: '+key)
    _need(value['optimizer_history_origin']=='fresh_from_immutable_zero_step_basis_for_explicit_role_objective'
          and value['initial_weights_sha256']==basis['weights_sha256']
          and _wire(value['implementation'])==_wire(_implementation()),'role state origin or implementation differs')
    modules['head']._state(value['model_state'],value['config'])
    _need(value['weights_sha256']==_digest(value['model_state']),'complete model state identity differs')
    steps=modules['weighted']._progress(value['progress'])
    modules['trainer']._optimizer_state(value['optimizer_state'],value['progress'],value['config'],modules['head'])
    _need(value['optimizer_state_sha256']==_digest(value['optimizer_state']),'complete named Adam identity differs')
    if not steps:
        _need(value['model_state']==basis['model_state'] and value['optimizer_state']==basis['optimizer_state']
              and value['initial_checkpoint_sha256'] is None and value['parent_checkpoint_sha256'] is None,
              'new objective must initialize exact basis weights and fresh Adam')
    else:
        _sha(value['initial_checkpoint_sha256'],'initial role checkpoint');_sha(value['parent_checkpoint_sha256'],'immediate role parent')
        initial=deepcopy(value)
        initial.update(model_state=deepcopy(basis['model_state']),weights_sha256=basis['weights_sha256'],
            optimizer_state=deepcopy(basis['optimizer_state']),optimizer_state_sha256=basis['optimizer_state_sha256'],
            progress=dict(optimizer_steps=0,epochs_completed=0,row_cursor=0),
            initial_checkpoint_sha256=None,parent_checkpoint_sha256=None)
        _need(value['initial_checkpoint_sha256']==_digest(initial),'initial role checkpoint lineage differs')
        if steps==1:_need(value['parent_checkpoint_sha256']==value['initial_checkpoint_sha256'],'first role update parent differs')
    _need(_wire(value['authority'])==_wire(AUTHORITY) and type(value['training_mask']) is type(value['evaluation_gold_mask']) is int
          and value['training_mask']==value['evaluation_gold_mask']==0,'role checkpoint grants no semantic eligibility')
    return value


def create(basis_checkpoint, *, expected_basis_checkpoint_sha256, expected_basis_policy_sha256, weighting='baseline'):
    """Fork the exact immutable zero-step basis into a new objective and lineage."""
    with _scope(dict(basis=basis_checkpoint,expected=expected_basis_checkpoint_sha256,
                     expected_policy=expected_basis_policy_sha256,weighting=weighting)) as (data,modules,_):
        basis=_basis(data['basis'],data['expected'],data['expected_policy'],modules)
        objective=_policy(data['weighting'],modules);inventories=_inventories(basis,objective,modules)
        value=dict(schema=SCHEMA,profile=PROFILE,architecture=ARCHITECTURE,input_dimension=384,
            vocabulary_size=537,max_total_ids=512,basis_checkpoint=basis,basis_checkpoint_sha256=data['expected'],
            basis_policy_sha256=data['expected_policy'],objective_policy=objective,objective_policy_sha256=_digest(objective),
            role_inventories=inventories,role_inventories_sha256=_digest(inventories),
            optimizer_history_origin='fresh_from_immutable_zero_step_basis_for_explicit_role_objective',
            initial_weights_sha256=basis['weights_sha256'],progress=dict(optimizer_steps=0,epochs_completed=0,row_cursor=0),
            initial_checkpoint_sha256=None,parent_checkpoint_sha256=None,implementation=_implementation(),
            authority=dict(AUTHORITY),training_mask=0,evaluation_gold_mask=0)
        for key in ('config','codec','codec_sha256','runtime','runtime_sha256','parameter_order','optimizer_config',
                    'adam_policy','update_policy','model_state','weights_sha256','optimizer_state','optimizer_state_sha256'):
            value[key]=deepcopy(basis[key])
        return _validate(value,_digest(value),_digest(objective),modules)


def checkpoint_sha256(checkpoint):
    with _scope(dict(checkpoint=checkpoint)) as (data,modules,_):
        return _digest(modules['runtime']._copy(data['checkpoint'],MAX_CHECKPOINT_BYTES))


def inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    with _scope(dict(checkpoint=checkpoint,expected=expected_checkpoint_sha256,expected_policy=expected_policy_sha256)) as (data,modules,_):
        value=_validate(data['checkpoint'],data['expected'],data['expected_policy'],modules)
        return dict(schema=SCHEMA,profile=PROFILE,checkpoint_sha256=data['expected'],objective_policy_sha256=data['expected_policy'],
            weighting=value['objective_policy']['weighting'],objective_kind='scope_conditional',
            basis_checkpoint_sha256=value['basis_checkpoint_sha256'],role_inventories_sha256=value['role_inventories_sha256'],
            weights_sha256=value['weights_sha256'],optimizer_state_sha256=value['optimizer_state_sha256'],
            progress=deepcopy(value['progress']),parameter_order=list(value['parameter_order']),
            model_constructed=False,optimizer_constructed=False,runtime_verified=False,checkpoint_schema_conversion=False,
            later_parent_is_commitment_not_replayed=value['progress']['optimizer_steps']>1,authority=dict(AUTHORITY))


def _row(value, modules):
    index=value['progress']['row_cursor'];basis=value['basis_checkpoint']
    stored=basis['rows_utf8'][index];inventory=value['role_inventories'][index]
    return dict(id=stored['id'],row_index=index,conditioning=deepcopy(stored['conditioning']),
        target_ids=list(inventory['target_ids']),position_weights=list(inventory['position_weights']),
        inventory_sha256=inventory['baseline_inventory_sha256'],
        baseline_inventory_sha256=inventory['baseline_inventory_sha256'],
        scope_inventory_sha256=inventory['scope_inventory_sha256'],role_inventory_sha256=_digest(inventory),
        policy_sha256=value['objective_policy_sha256'],objective_kind='scope_conditional',
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
    """Restore actual role-state tensors and named Adam through original owners."""
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
            _need(weights==value['model_state'] and moments==value['optimizer_state'],'exact named role restore differs')
            return model,optimizer
        finally:
            fence()
            _need(torch.equal(rng,torch.get_rng_state()) and _wire(weighted._numeric(modules)[2])==_wire(runtime),
                  'restoration changed CPU RNG or numerical runtime')


def objective(checkpoint, logits, *, expected_checkpoint_sha256, expected_policy_sha256):
    """One conditional role-weighted scalar; no model, backward or update."""
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
            losses=torch.nn.functional.cross_entropy(flat.masked_fill(~allowed,-torch.inf),labels,ignore_index=0,reduction='none')
            with torch.no_grad():full=torch.nn.functional.cross_entropy(flat,labels,ignore_index=0,reduction='none')
            loss=(losses*weights).sum()/weights.sum()
            _need(loss.ndim==0 and loss.requires_grad and bool(torch.isfinite(loss))
                  and bool(torch.isfinite(losses).all()) and bool(torch.isfinite(full).all()),'finite conditional role objective required')
            report=dict(schema='legal-compact-role-objective-observation/v1',checkpoint_sha256=data['expected'],
                objective_policy_sha256=data['expected_policy'],objective_kind='scope_conditional',weighting=value['objective_policy']['weighting'],
                basis_checkpoint_sha256=value['basis_checkpoint_sha256'],row_id=row['id'],row_index=row['row_index'],
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
                reduction='scope_masked_none_role_weighted_sum_divide67',full537_logits_observed=True,
                full537_vocabulary=False,conditional_allowed_set_loss=True,singleton_zero_loss_is_not_accuracy=True,
                full537_and_conditional_losses_not_comparable_as_accuracy=True,teacher_forcing=True,
                forward_performed=False,backward_performed=False,optimizer_update_performed=False,
                structural_role_priority_is_not_semantic_verification=True,authority=dict(AUTHORITY))
            return loss,report
        finally:
            fence()
            _need(logits._version==version and torch.equal(saved,logits.detach()) and torch.equal(rng,torch.get_rng_state())
                  and _wire(weighted._numeric(modules)[2])==_wire(runtime),'objective mutated input/RNG or runtime')


def pack(model, optimizer, checkpoint, progress, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Commit exactly one actual named update under the new role objective."""
    with _scope(dict(checkpoint=checkpoint,progress=progress,expected=expected_checkpoint_sha256,
                     expected_policy=expected_policy_sha256)) as (data,modules,fence):
        value=_validate(data['checkpoint'],data['expected'],data['expected_policy'],modules)
        weighted=modules['weighted'];steps=weighted._progress(data['progress'])
        _need(steps==value['progress']['optimizer_steps']+1,'role packing must advance exactly one actual update')
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


__all__=['RoleTrainingError','create','checkpoint_sha256','inspect','training_row','restore','objective','pack']
