"""Finite CP128 warm-start objective, complete-state and saved-resume regression.

Invoke run_qualification inside the existing owned validation worker with the
original admitted checkpoint. Six physical updates cover two unique steps and
one saved-step replay in each objective. No generation or encoder is invoked.
The independently computed standard-library softmax checks actual same-backward
logit gradients, including zero versus nonzero singleton learning signals.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

SELECTED = ['contract_guards','scope_conditional_steps','scope_conditional_resume','full537_steps','full537_resume']


def need(ok, message):
    if not ok:
        raise ValueError(message)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def analytic_objective(logits, labels, allowed, weights, observed_loss, gradient):
    """Independent standard-library softmax/weighted-CE and same-backward check."""
    need(len(logits)==1 and len(logits[0])==len(labels)==len(allowed)==len(weights)==46
         and math.fsum(weights)==67.0,'fixed complete objective geometry')
    losses=[];maximum_error=0.0;coordinates=0;nonzero_positions=0
    need(len(gradient)==1 and len(gradient[0])==46,'complete observed logit gradient')
    for index,(scores,target,choices,weight) in enumerate(zip(logits[0],labels,allowed,weights)):
        need(len(scores)==len(gradient[0][index])==537 and target in choices
             and choices==sorted(set(choices)) and all(math.isfinite(x) for x in scores),
             'bounded finite logits and denominator required')
        peak=max(scores[token] for token in choices)
        exps={token:math.exp(scores[token]-peak) for token in choices}
        denominator=math.fsum(exps.values())
        losses.append((math.log(denominator)+peak-scores[target])*weight/67.0)
        nonzero_positions+=len(choices)>1
        for token,actual in enumerate(gradient[0][index]):
            expected=(exps[token]/denominator-(token==target))*weight/67.0 if token in exps else 0.0
            need(math.isfinite(actual) and math.isclose(actual,expected,rel_tol=3e-5,abs_tol=2e-8),
                 'observed same-backward gradient differs from analytic role objective')
            if len(choices)==1 or token not in exps:
                need(actual==0.0,'singleton/forbidden conditional gradient must be exactly zero')
            maximum_error=max(maximum_error,abs(actual-expected));coordinates+=1
    independent_loss=math.fsum(losses)
    need(math.isclose(observed_loss,independent_loss,rel_tol=3e-6,abs_tol=2e-6),
         'observed loss differs from independently recomputed objective')
    return dict(weighted_loss=independent_loss,observed_loss=observed_loss,
                checked_logit_gradient_coordinates=coordinates,
                max_absolute_logit_gradient_error=maximum_error,
                nontrivial_positions=nonzero_positions,singleton_positions=46-nonzero_positions,
                active_denominator_singleton_and_forbidden_gradients_exact_zero_where_required=True,
                does_not_reexecute_GRU_differentiation=True)


def run_qualification(*, owner, parent, torch, save, read_saved):
    """Observe exactly four restores/six updates using the unchanged saved assets."""
    parent_hash = digest(parent)
    need(parent_hash == '2c6b5201e1223c3c25adc07b11062180fbaf5f46ce3c078c5b96395f8d87225a'
         and parent['weights_sha256'] == 'd4e7c710a8aba4462aab575d9bbfb4278c1870fadaf304f80d0f341af4912c34',
         'original CP128 parent weights and checkpoint required')
    basis = parent['basis_checkpoint']
    artifacts, patches, handles, resumes = {}, [], [], []
    roster = [dict(label=name,status='not_started') for name in SELECTED]
    counts = dict(model_allocations=0, adam_allocations=0, optimizer_base_allocations=0,
        model_forward_entered=0, model_forward_completed=0, gru_entered=0, gru_completed=0,
        backward_entered=0, backward_completed=0, gradient_clip_calls=0,
        optimizer_step_entered=0, optimizer_step_completed=0, logits_gradient_hook_calls=0,
        autograd_grad_calls=0, forbidden_calls=0, refused_nonfinite_logits_calls=0)
    active = dict(phase='pure',label=None,checkpoint=None,model=None,optimizer=None,item=None,loss=None)
    rng = torch.get_rng_state().clone()
    runtime, trainer, head, loaded = None, None, None, None

    def put(name, value):
        need(Path(name).name == name and name not in artifacts, 'fresh direct artifact required')
        before = digest(value)
        item = save(name,value)
        need(digest(value) == before and Path(item['path']).name == name, 'save changed report')
        artifacts[name] = item
        return item

    def saved(name):
        item = artifacts[name]
        raw = read_saved(item)
        need(len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'],
             'saved checkpoint or report differs')
        return json.loads(raw)

    def options(cp):
        return dict(expected_checkpoint_sha256=digest(cp),expected_policy_sha256=cp['objective_policy_sha256'])

    def patch(owner,name,replacement):
        patches.append((owner,name,getattr(owner,name)))
        setattr(owner,name,replacement)

    def fence():
        need(digest(parent) == parent_hash and torch.equal(rng,torch.get_rng_state())
             and not torch.cuda.is_initialized() and not torch.is_autocast_enabled('cpu'), 'request/RNG/device drift')
        if runtime is not None:
            need(trainer._runtime(head,loaded) == runtime, 'runtime drift')

    def observed(ok,message):
        if not ok:
            counts['forbidden_calls'] += 1
        need(ok,message)

    def mark(label,status):
        row = next(row for row in roster if row['label'] == label)
        need((row['status'],status) in [('not_started','entered'),('entered','completed')], 'slot repeated')
        row['status'] = status

    def model_state(model):
        cp = active['checkpoint']
        need(list(model.state_dict()) == cp['parameter_order'], 'model parameter order differs')
        return {name:tensor.detach().tolist() for name,tensor in model.state_dict().items()}

    def gradients():
        result = {}
        for name,parameter in active['model'].named_parameters():
            need(parameter.grad is not None and parameter.grad.dtype is torch.float32
                 and parameter.grad.device.type == 'cpu' and bool(torch.isfinite(parameter.grad).all()), 'finite full gradient required')
            result[name] = parameter.grad.detach().tolist()
        need(list(result) == active['checkpoint']['parameter_order'], 'complete gradient order differs')
        return result

    try:
        put('roster.json',dict(slots=deepcopy(roster),physical_training_updates=6,generation_forwards=0))
        from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_role_training_v1 as old_role
        from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_training_v2 as trainer
        head,_ = trainer._head()
        loaded = head._owners(numeric=True)
        numerical = loaded['modules']['numerical']
        runtime = trainer._runtime(head,loaded)
        need(parent['runtime'] == runtime, 'original CP128 runtime required')
        real_model,real_adam,real_base = numerical._model,torch.optim.Adam.__init__,torch.optim.Optimizer.__init__
        real_gru,real_backward = torch.nn.GRU.forward,torch.autograd.backward
        real_clip,real_step = torch.nn.utils.clip_grad_norm_,torch.optim.Adam.step

        def before_forward(model,args):
            observed(active['phase'] == 'train' and model is active['model'] and active['item'] is None
                     and counts['model_forward_entered'] < 6, 'undeclared forward')
            cp = active['checkpoint'];index = cp['progress']['row_cursor'];row = basis['rows_utf8'][index]
            vector,prefix = args
            need(vector.dtype is torch.float32 and vector.device.type == 'cpu' and list(vector.shape) == [1,384]
                 and vector.detach().tolist()[0] == torch.tensor(row['conditioning'],dtype=torch.float32).tolist()
                 and prefix.dtype is torch.long and prefix.device.type == 'cpu'
                 and prefix.detach().tolist() == [basis['inventories'][index]['target_ids'][:-1]]
                 and model.training and torch.is_grad_enabled() and not torch.is_inference_mode_enabled()
                 and model_state(model) == cp['model_state'], 'actual teacher-forced input/state/mode differs')
            active['item'] = dict(label=active['label'],before_checkpoint_sha256=digest(cp),row_index=index,
                teacher_prefix_ids=prefix.detach().tolist()[0],conditioning_sha256=digest(vector.detach().tolist()[0]),
                before_weights_sha256=cp['weights_sha256'],before_moments_sha256=cp['optimizer_state_sha256'],
                gru=False,backward=False,clipped=False,updated=False,logits_gradient=None)
            counts['model_forward_entered'] += 1

        def after_forward(model,args,output):
            item = active['item'];projected,logits = output
            observed(item is not None and item['gru'] and model is active['model'], 'forward completion without declared GRU')
            need(list(projected.shape) == [1,384] and list(logits.shape) == [1,46,537]
                 and logits.requires_grad and logits.dtype is torch.float32 and logits.device.type == 'cpu'
                 and bool(torch.isfinite(projected).all()) and bool(torch.isfinite(logits).all()), 'finite full537 training output required')
            item['full_sequence_logits'] = logits.detach().tolist()
            item['full_sequence_logits_sha256'] = digest(item['full_sequence_logits'])
            def logit_gradient(value):
                observed(active['item'] is item and item['logits_gradient'] is None, 'extra logits gradient hook')
                need(list(value.shape) == [1,46,537] and bool(torch.isfinite(value).all()), 'finite actual logits gradient required')
                item['logits_gradient'] = value.detach().tolist()
                counts['logits_gradient_hook_calls'] += 1
            handles.append(logits.register_hook(logit_gradient))
            counts['model_forward_completed'] += 1

        def construct_model(*args,**kwargs):
            observed(active['phase'] == 'restore' and active['model'] is None and counts['model_allocations'] < 4,
                     'undeclared model construction')
            counts['model_allocations'] += 1
            model = real_model(*args,**kwargs);active['model'] = model
            handles.extend((model.register_forward_pre_hook(before_forward),model.register_forward_hook(after_forward)))
            return model

        def construct_adam(opt,*args,**kwargs):
            observed(active['phase'] == 'restore' and active['optimizer'] is None and counts['adam_allocations'] < 4,
                     'undeclared Adam construction')
            counts['adam_allocations'] += 1
            result = real_adam(opt,*args,**kwargs);active['optimizer'] = opt
            return result

        def construct_base(opt,*args,**kwargs):
            observed(active['phase'] == 'restore' and counts['optimizer_base_allocations'] + 1 == counts['adam_allocations'],
                     'undeclared optimizer base construction')
            counts['optimizer_base_allocations'] += 1
            return real_base(opt,*args,**kwargs)

        def gru(module,*args,**kwargs):
            item = active['item']
            observed(item is not None and not item['gru'] and module is active['model'].decoder
                     and counts['gru_entered'] < 6, 'undeclared GRU')
            counts['gru_entered'] += 1
            answer = real_gru(module,*args,**kwargs)
            counts['gru_completed'] += 1;item['gru'] = True
            return answer

        def backward(*args,**kwargs):
            item = active['item']
            observed(active['phase'] == 'train' and item is not None and item['gru'] and not item['backward']
                     and counts['backward_entered'] < 6, 'undeclared backward')
            offered = args[0] if args else kwargs.get('tensors')
            if isinstance(offered,(tuple,list)):
                need(len(offered)==1,'one differentiated scalar required');offered=offered[0]
            need(offered is active['loss'] and offered.ndim==0 and bool(torch.isfinite(offered)),
                 'the declared role objective must be the actual backward scalar')
            item['actual_backward_loss']=float(offered.detach())
            counts['backward_entered'] += 1
            answer = real_backward(*args,**kwargs)
            counts['backward_completed'] += 1;item['backward'] = True
            return answer

        def clip(parameters,*args,**kwargs):
            item = active['item'];offered = list(parameters);expected = list(active['model'].parameters())
            observed(item is not None and item['backward'] and not item['clipped']
                     and len(offered) == len(expected) and all(x is y for x,y in zip(offered,expected))
                     and args == (5.0,) and kwargs == {'error_if_nonfinite':True}, 'undeclared gradient clipping')
            item['preclip_gradients'] = gradients()
            result = real_clip(offered,*args,**kwargs)
            item['postclip_gradients'] = gradients();item['preclip_global_L2_Torch'] = float(result)
            counts['gradient_clip_calls'] += 1;item['clipped'] = True
            return result

        def adam_step(opt,*args,**kwargs):
            item = active['item']
            observed(opt is active['optimizer'] and item is not None and item['clipped'] and not item['updated']
                     and not args and not kwargs and counts['optimizer_step_entered'] < 6, 'undeclared Adam step')
            counts['optimizer_step_entered'] += 1
            result = real_step(opt)
            counts['optimizer_step_completed'] += 1;item['updated'] = True
            weights,moments = numerical._pack(active['model'],opt)
            item['actual_after_weights_sha256'],item['actual_after_moments_sha256'] = digest(weights),digest(moments)
            return result

        def deny(*args,**kwargs):
            counts['autograd_grad_calls'] += 1;counts['forbidden_calls'] += 1
            raise RuntimeError('extra differentiation forbidden')

        for obj,name,replacement in [(numerical,'_model',construct_model),(torch.optim.Adam,'__init__',construct_adam),
            (torch.optim.Optimizer,'__init__',construct_base),(torch.nn.GRU,'forward',gru),
            (torch.autograd,'backward',backward),(torch.autograd,'grad',deny),
            (torch.nn.utils,'clip_grad_norm_',clip),(torch.optim.Adam,'step',adam_step)]:
            patch(obj,name,replacement)
        mark('contract_guards','entered')
        initials, guards, create_guards = {}, [], []
        parent_options = dict(expected_parent_checkpoint_sha256=parent_hash,
                              expected_parent_policy_sha256=parent['objective_policy_sha256'])
        for case in ('wrong_parent_commitment','wrong_parent_policy','unknown_objective'):
            opts = dict(parent_options)
            objective_kind = 'scope_conditional'
            if case == 'wrong_parent_commitment': opts['expected_parent_checkpoint_sha256'] = '0'*64
            elif case == 'wrong_parent_policy': opts['expected_parent_policy_sha256'] = '0'*64
            else: objective_kind = 'unknown'
            error = None
            try: owner.create(parent, objective_kind=objective_kind, **opts)
            except ValueError as failed: error = dict(type=type(failed).__name__,message=str(failed)[:1000])
            need(error is not None and all(value == 0 for value in counts.values()),
                 'constructor refusal accepted or allocated a model/optimizer')
            create_guards.append(dict(case=case,refused=True,error=error,counts=deepcopy(counts)))

        cases = ('wrong_expected_policy_digest','unknown_objective','altered_parent',
                 'historical_adam_at_zero','authority_promotion','bool_progress',
                 'wrong_initial_weights','wrong_dimension','old_role_rejects_successor',
                 'initial_lineage_at_zero','wrong_vocabulary','wrong_architecture')
        for arm in ('scope_conditional','full537'):
            cp = owner.create(parent, objective_kind=arm, **parent_options)
            need(cp['schema'] == owner.SCHEMA and cp['runtime'] == runtime
                 and cp['warmstart_parent_checkpoint'] == parent
                 and cp['model_state'] == parent['model_state']
                 and cp['optimizer_state']['parameters'] == {}
                 and cp['progress'] == dict(optimizer_steps=0,epochs_completed=0,row_cursor=0),
                 'warm start must inherit every CP128 tensor and use empty fresh Adam')
            inspected = owner.inspect(cp, **options(cp))
            row = owner.training_row(cp, **options(cp))
            independent_weights = [4.5 if position in (9,14,19,21,32,38) else 1.0
                                   for position in range(1,47)]
            need(inspected['model_constructed'] is inspected['optimizer_constructed'] is False
                 and row['position_weights'] == independent_weights
                 and math.fsum(row['position_weights']) == 67.0
                 and cp['initial_weights_sha256'] == parent['weights_sha256']
                 and len(cp['model_state']) == 13,
                 'independent original semantic-priority mass and full tensor inventory required')
            initials[arm] = cp
            put(arm+'-step-0.json',cp)
            for case in cases:
                bad = deepcopy(cp)
                policy = bad['objective_policy_sha256']
                if case == 'wrong_expected_policy_digest': policy = '0'*64
                elif case == 'unknown_objective':
                    bad['objective_policy']['objective_kind'] = 'unknown'
                    bad['objective_policy_sha256'] = policy = digest(bad['objective_policy'])
                elif case == 'altered_parent':
                    bad['warmstart_parent_checkpoint']['progress']['optimizer_steps'] = 126
                    bad['warmstart_parent_checkpoint_sha256'] = digest(bad['warmstart_parent_checkpoint'])
                elif case == 'historical_adam_at_zero':
                    bad['optimizer_state'] = deepcopy(parent['optimizer_state'])
                    bad['optimizer_state_sha256'] = digest(bad['optimizer_state'])
                elif case == 'authority_promotion': bad['authority']['production_ready'] = True
                elif case == 'bool_progress': bad['progress']['optimizer_steps'] = False
                elif case == 'wrong_initial_weights': bad['initial_weights_sha256'] = '0'*64
                elif case == 'wrong_dimension': bad['input_dimension'] = 768
                elif case == 'initial_lineage_at_zero': bad['initial_checkpoint_sha256'] = parent_hash
                elif case == 'wrong_vocabulary': bad['vocabulary_size'] = 536
                elif case == 'wrong_architecture': bad['architecture'] = 'unknown/v1'
                elif case != 'old_role_rejects_successor': raise ValueError('unregistered refusal')
                error = None
                try:
                    chosen = old_role if case == 'old_role_rejects_successor' else owner
                    chosen.restore(bad, expected_checkpoint_sha256=digest(bad), expected_policy_sha256=policy)
                except ValueError as failed: error = dict(type=type(failed).__name__,message=str(failed)[:1000])
                need(error is not None and all(value == 0 for value in counts.values()),
                     'metadata refusal accepted or allocated numerical state')
                guards.append(dict(arm=arm,case=case,refused=True,error=error,counts=deepcopy(counts)))
        need(len(guards) == 24 and len(create_guards) == 3
             and initials['scope_conditional']['model_state'] == initials['full537']['model_state']
             and initials['scope_conditional']['optimizer_state'] == initials['full537']['optimizer_state'],
             'complete matched fresh-Adam cohort required')
        put('pure-contract-guards.json',dict(cases=guards,create_cases=create_guards,
                                           actual_counts=deepcopy(counts),learned_success_claimed=False))
        mark('contract_guards','completed')
        fence()

        def restore(cp,label):
            active.update(phase='restore',label=label,checkpoint=cp,model=None,optimizer=None,item=None,loss=None)
            model,opt = owner.restore(cp,**options(cp))
            need(model is active['model'] and opt is active['optimizer']
                 and model_state(model) == cp['model_state'], 'actual restored weights differ')
            weights,moments = numerical._pack(model,opt)
            need(weights == cp['model_state'] and moments == cp['optimizer_state'], 'actual restored named state differs')
            return model,opt

        def step(cp,model,opt,label,*,nan_guard=False):
            active.update(phase='train',label=label,checkpoint=cp,model=model,optimizer=opt,item=None,loss=None)
            row = owner.training_row(cp,**options(cp))
            need(len(row['scope_allowed_token_ids']) == len(row['position_weights']) == 46
                 and sum(row['position_weights']) == 67, 'fixed complete loss masks/normalizer required')
            model.train();opt.zero_grad(set_to_none=True)
            vector = torch.tensor([row['conditioning']],dtype=torch.float32,device='cpu')
            prefix = torch.tensor([row['target_ids'][:-1]],dtype=torch.long,device='cpu')
            started,cpu = time.perf_counter(),time.thread_time()
            projected,logits = model(vector,prefix)
            rejected = None
            if nan_guard:
                forbidden = next(token for token in range(537) if token not in row['scope_allowed_token_ids'][0])
                bad_logits = logits.clone()
                with torch.no_grad():
                    bad_logits[0,0,forbidden] = float('nan')
                try:
                    owner.objective(cp,bad_logits,**options(cp))
                except ValueError as error:
                    rejected = dict(type=type(error).__name__,message=str(error)[:1000],position=0,forbidden_token_id=forbidden)
                need(rejected is not None and bool(torch.isfinite(logits).all()), 'nonfinite forbidden coordinate accepted or original mutated')
                counts['refused_nonfinite_logits_calls'] += 1
            loss,objective = owner.objective(cp,logits,**options(cp))
            need(loss.ndim == 0 and loss.requires_grad and bool(torch.isfinite(loss)), 'finite differentiable scalar required')
            active['loss'] = loss
            loss.backward()
            analytic_allowed = (row['scope_allowed_token_ids'] if cp['objective_policy']['objective_kind'] == 'scope_conditional'
                                else [list(range(537)) for _ in range(46)])
            analytic=analytic_objective(active['item']['full_sequence_logits'],row['target_ids'][1:],
                analytic_allowed,row['position_weights'],float(loss.detach()),
                active['item']['logits_gradient'])
            torch.nn.utils.clip_grad_norm_(list(model.parameters()),5.0,error_if_nonfinite=True)
            opt.step()
            item = active['item'];next_step = cp['progress']['optimizer_steps']+1
            successor = owner.pack(model,opt,cp,dict(optimizer_steps=next_step,epochs_completed=next_step//2,row_cursor=next_step%2),**options(cp))
            need(successor['warmstart_parent_checkpoint']==parent and item['updated'] and item['logits_gradient'] is not None
                 and successor['weights_sha256'] == item['actual_after_weights_sha256']
                 and successor['optimizer_state_sha256'] == item['actual_after_moments_sha256']
                 and successor['parent_checkpoint_sha256'] == digest(cp)
                 and successor['objective_policy_sha256'] == cp['objective_policy_sha256'], 'actual packed successor differs')
            report = dict(schema='legal-ir-role-training-observed-step/v1',label=label,
                before_checkpoint_sha256=digest(cp),after_checkpoint_sha256=digest(successor),
                checkpoint_progress=successor['progress'],row_id=row['id'],row_index=row['row_index'],
                objective_kind=cp['objective_policy']['objective_kind'],weighting='semantic_priority',objective_policy_sha256=cp['objective_policy_sha256'],
                basis_checkpoint_sha256=digest(basis),role_inventory=deepcopy(parent['role_inventories'][row['row_index']]),
                target_ids=row['target_ids'],label_ids=row['target_ids'][1:],position_weights=row['position_weights'],weight_sum=67,
                scope_allowed_token_ids=row['scope_allowed_token_ids'],loss=float(loss.detach()),objective_report=objective,
                full_sequence_logits=item['full_sequence_logits'],logits_gradient=item['logits_gradient'],
                preclip_gradients=item['preclip_gradients'],postclip_gradients=item['postclip_gradients'],
                preclip_global_L2_Torch=item['preclip_global_L2_Torch'],global_clip_max_norm=5.0,
                actual_observation={key:value for key,value in item.items()
                    if key not in ('full_sequence_logits','logits_gradient','preclip_gradients','postclip_gradients')},
                refused_nonfinite_logits=rejected,teacher_forced=True,training_exposed=True,
                independently_checked_objective=analytic,
                training_mask=0,evaluation_gold_mask=0,source_encoder_authenticated=False,
                timing=dict(inclusive_wall_seconds=time.perf_counter()-started,inclusive_thread_cpu_seconds=time.thread_time()-cpu))
            for key in ('full_sequence_logits','logits_gradient','preclip_gradients','postclip_gradients'):
                report[key+'_sha256'] = digest(report[key])
            put(label+'.json',successor);put(label+'-report.json',report)
            active.update(phase='pure',item=None,loss=None)
            fence()
            return successor

        for arm in ('scope_conditional','full537'):
            mark(arm+'_steps','entered')
            cp = initials[arm];model,opt = restore(cp,arm+'_steps')
            cp1 = step(cp,model,opt,arm+'-step-1',nan_guard=True)
            cp2 = step(cp1,model,opt,arm+'-step-2')
            mark(arm+'_steps','completed')
            active.update(phase='pure',model=None,optimizer=None,checkpoint=None)
            mark(arm+'_resume','entered')
            saved1 = saved(arm+'-step-1.json');model,opt = restore(saved1,arm+'_resume')
            repeated = step(saved1,model,opt,arm+'-resume-step-2')
            need(wire(repeated) == wire(cp2) == wire(saved(arm+'-step-2.json')), 'saved resume entire checkpoint differs')
            resumes.append(dict(arm=arm,sequential=artifacts[arm+'-step-2.json'],resumed=artifacts[arm+'-resume-step-2.json'],
                exact_complete_checkpoint=True,checkpoint_sha256=digest(cp2),additional_physical_updates=1))
            mark(arm+'_resume','completed');active.update(phase='pure',model=None,optimizer=None,checkpoint=None)
            fence()
        expected = dict(model_allocations=4,adam_allocations=4,optimizer_base_allocations=4,
            model_forward_entered=6,model_forward_completed=6,gru_entered=6,gru_completed=6,
            backward_entered=6,backward_completed=6,gradient_clip_calls=6,optimizer_step_entered=6,optimizer_step_completed=6,
            logits_gradient_hook_calls=6,autograd_grad_calls=0,forbidden_calls=0,refused_nonfinite_logits_calls=2)
        need(counts == expected and len(resumes)==2,
             'declared physical work or complete comparison count differs')
        conditional_first = saved('scope_conditional-step-1-report.json')
        full_first = saved('full537-step-1-report.json')
        need(conditional_first['full_sequence_logits'] == full_first['full_sequence_logits']
             and conditional_first['position_weights'] == full_first['position_weights']
             and conditional_first['logits_gradient'] != full_first['logits_gradient']
             and conditional_first['loss'] != full_first['loss'],
             'same complete zero-update logits/weights must produce the declared objective intervention')
        singleton_contrast = []
        for row_index in range(2):
            conditional_report = saved('scope_conditional-step-'+str(row_index+1)+'-report.json')
            full_report = saved('full537-step-'+str(row_index+1)+'-report.json')
            for position,choices in enumerate(conditional_report['scope_allowed_token_ids']):
                if len(choices) == 1:
                    cg = conditional_report['logits_gradient'][0][position]
                    fg = full_report['logits_gradient'][0][position]
                    need(all(x == 0.0 for x in cg) and any(x != 0.0 for x in fg),
                         'singleton conditional zero-gradient/full537 nonzero-gradient contrast failed')
                    singleton_contrast.append(dict(row_index=row_index,target_position=position+1,
                        conditional_gradient_exact_zero=True,full537_gradient_nonzero=True))
        need(len(singleton_contrast) == 78, 'complete singleton gradient population required')
        resume_fields = ('loss','full_sequence_logits','logits_gradient','preclip_gradients',
                         'postclip_gradients','preclip_global_L2_Torch','target_ids','label_ids',
                         'position_weights','scope_allowed_token_ids')
        for arm in ('scope_conditional','full537'):
            sequential = saved(arm+'-step-2-report.json')
            repeated = saved(arm+'-resume-step-2-report.json')
            need(all(wire(sequential[key]) == wire(repeated[key]) for key in resume_fields),
                 'saved resume changed actual forward/backward/gradient/clip observations')
        put('intervention-observation.json',dict(zero_update_paired_logits_equal=True,
            first_loss_and_logits_gradients_differ=True,same_semantic_priority_weights=True,
            same_CP128_weights_and_fresh_Adam=True,singleton_contrast=singleton_contrast,
            candidate_reconstruction_improvement_measured=False))
        put('actual-counts.json',counts)
        put('resume-comparisons.json',dict(arms=resumes,exact_observation_fields=list(resume_fields)))
        put('final-roster.json',dict(slots=roster))
        summary = dict(status='pass',completed_checks=SELECTED,actual_gru_forward_count=6,backward_calls=6,
            optimizer_updates=6,optimizer_allocations=4,model_allocations=4,training_performed=True,generation_performed=False,
            pure_negative_guards=24,create_negative_guards=3,refused_nonfinite_logits_calls=2,resume_comparisons=2,
            zero_update_paired_logits_equal=True,singleton_gradient_contrasts=78,
            unique_optimizer_steps_per_arm=2,additional_physical_resume_updates=2,
            source_encoder_authenticated=False,legal_or_holdout_accuracy_established=False,reconstruction_efficacy_measured=False)
        put('result.json',summary)
        put('manifest.json',dict(schema='legal-ir-cp128-warmstart-qualification-artifacts/v1',
            artifacts=deepcopy(artifacts),counts=counts,parent_checkpoint_sha256=parent_hash))
        fence()
        return summary
    except BaseException as error:
        for row in roster:
            if row['status'] == 'entered':
                row.update(status='failed',error_type=type(error).__name__)
        put('failure.json',dict(error_type=type(error).__name__,message=str(error)[:2000],counts=deepcopy(counts),slots=deepcopy(roster)))
        raise
    finally:
        for handle in handles:
            handle.remove()
        for obj,name,previous in reversed(patches):
            setattr(obj,name,previous)
