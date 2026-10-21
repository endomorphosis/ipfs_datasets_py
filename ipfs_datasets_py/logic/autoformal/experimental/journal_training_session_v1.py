"""Owned unweighted compact384 training with an explicit journal checkpoint.

Source-only candidate until separately admitted. The original a1ad helper strictly
validates/restores the embedded legacy step8 anchor once. Each numerical transition
uses its unchanged complete dynamic model/named-Adam exporter, but does not call
the legacy full checkpoint validator or packer. No intermediate legacy checkpoint
SHA is invented. Source/native admission, durability and independent physical-call
observation remain with the caller. This module supplies no semantic authority.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import threading
import time

from . import _legacy_source_bridge_v1 as _bridge

_PORTED_SOURCE_SHA256 = _bridge.source_reference('journal_session')["sha256"]

SCHEMA = 'legal-gated-journal-training-checkpoint/v1'
PROFILE = 'authored-compact384-unweighted-journal-training-development/v1'
SESSION_SCHEMA = 'legal-gated-journal-training-session/v1'
STEP_SCHEMA = 'legal-gated-journal-training-step/v1'
NUMERIC_SCHEMA = 'legal-gated-journal-training-numeric-adapter/v1'
MAX_STEPS = 3
MAX_CHECKPOINT_BYTES = 8 * 1024**2
MAX_REPORT_BYTES = 3 * 1024**2
MAX_PARTIAL_BYTES = 8 * 1024**2
STATE_SHA = 'a1ad93184fbf417b704c801ce6c15b932f0d138974f4f020239c7cbb4e0493a3'
CANDIDATE_SHA = 'dd91a47e8c116ea2cb6daa60716f0c452b82585df78d4c88756a1147eb55ba00'
ANCHORS = {
    'h0_only':'56e26631c111ce684f564f89d83f25f7221fa1f80f21d02a9346d93306d83903',
    'gated_per_step':'e652f9f0e4ef5280a4f08b439a7f2069228bc75748297d04a334ff7c8c344c38',
}
AUTHORITY = {name:False for name in ('source_encoder_authenticated','statutory_accuracy',
    'heldout_accuracy','graph_admission','Lean_admission','production_ready','native_admission')}
COUNTERS = ('model_restore_entered','model_restore_completed','optimizer_restore_entered',
    'optimizer_restore_completed','model_forward_entered','model_forward_completed',
    'GRU_entered','GRU_completed','backward_entered','backward_completed',
    'Adam_step_entered','Adam_step_completed','dynamic_state_exports')
CP_FIELDS = {'schema','profile','arm','legacy_anchor','legacy_anchor_sha256','implementation',
    'session_policy','model_state','weights_sha256','model_buffers','parameter_order','optimizer_state',
    'optimizer_state_sha256','optimizer_policy','parameter_groups','progress','journal','journal_head_sha256',
    'spent_updates','accounting','previous_journal_checkpoint_sha256','authority','training_mask','evaluation_gold_mask'}
ENTRY_FIELDS = {'schema','ordinal','new_step','row_index','row_id','row_sha256','previous_digest',
    'before_weights_sha256','after_weights_sha256','before_Adam_state_sha256','after_Adam_state_sha256',
    'full_sequence_logits_sha256','preclip_gradients_sha256','postclip_gradients_sha256','loss',
    'actual_GRUs','actual_backwards','actual_Adam_steps'}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


class JournalTrainingError(ValueError):
    """Closed journal profile, ownership, numerical or lifetime invariant failed."""


def _need(condition,message):
    if not condition:
        raise JournalTrainingError(message)


def _wire(value,maximum=MAX_CHECKPOINT_BYTES):
    try:
        body = json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
            allow_nan=False).encode()
    except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError) as error:
        raise JournalTrainingError('bounded ordinary finite JSON required') from error
    _need(len(body) <= maximum,'declared complete JSON envelope exceeded')
    return body


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(value):
    return type(value) is str and len(value) == 64 and set(value) <= set('0123456789abcdef')


def _source(path,expected):
    path = Path(path)
    _need(path.is_absolute() and path.resolve(strict=True) == path,'plain absolute source required')
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 1024**2,
        'bounded single-link source required')
    body = path.read_bytes();after = path.lstat()
    witness = lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
    _need(witness(before) == witness(after) and len(body) == before.st_size
        and hashlib.sha256(body).hexdigest() == expected,'source bytes or identity changed')
    return {'path':str(path),'bytes':len(body),'sha256':expected},witness(after)


def _owners():
    from . import gated_training_state_v1 as subject
    from . import gated_conditioning_v1 as candidate
    state_ref = _bridge.require_module("gated_training_state", subject)
    candidate_ref = _bridge.require_module("gated_conditioning", candidate)
    state_source = _source(subject.__file__, state_ref["sha256"])
    candidate_source = _source(candidate.__file__, candidate_ref["sha256"])
    self_source = _source(_SELF_PATH, _SELF_SHA)
    canonical = candidate._sources()
    return subject, candidate, {"session": self_source[0], "training_state": state_source[0],
        "gated_candidate": candidate_source[0], "canonical_owners": canonical,
        "source_profile_bridge_sha256": _bridge.implementation_sha256()}


def _copy(value,candidate):
    try:
        result = candidate._copy(value)
    except candidate.GatedConditioningError as error:
        raise JournalTrainingError('bounded ordinary finite checkpoint required') from error
    _wire(result)
    return result


def _tensor(value,shape,nonnegative=False):
    if shape:
        _need(type(value) is list and len(value) == shape[0],'complete dynamic tensor shape differs')
        for child in value:_tensor(child,shape[1:],nonnegative)
    else:
        _need(type(value) is float and math.isfinite(value) and (not nonnegative or value >= 0),
            'finite plain float32 coordinate required')
        try:rounded = struct.unpack('!f',struct.pack('!f',value))[0]
        except (OverflowError,struct.error) as error:
            raise JournalTrainingError('dynamic tensor float32 overflow') from error
        _need(rounded.hex() == value.hex(),'exact exported float32 coordinate required')


def _policy(max_steps,cadence):
    _need(type(max_steps) is int and max_steps == MAX_STEPS,'exact three-transition cumulative session budget required')
    _need(type(cadence) is int and cadence == 2,'exact two-transition checkpoint cadence required')
    return {'max_steps_from_legacy_anchor':max_steps,'checkpoint_cadence':cadence,
        'final_tail_checkpoint_permitted':True,'input_dimension':384,'vocabulary_size':537,
        'loss':'full537_sequence_cross_entropy','ignore_index':0,'global_clip_L2':5.0,
        'row_order':'original_two_rows_repeated','batch_size':1,'dtype':'float32','device':'cpu',
        'physical_budgets_carry_across_resume':True,'maximum_unrecorded_transition_tail':1,
        'maximum_unrecoverable_updates_without_published_checkpoint':cadence,
        'journal_is_not_a_recovery_point':True,'checkpoint_durability_owned_by_caller':True}


def _numeric(value,anchor,subject):
    shapes = subject._shapes(anchor['arm'])
    order = list(shapes)
    _need(type(value['model_state']) is dict and type(value['parameter_order']) is list
        and value['parameter_order'] == order
        and set(value['model_state']) == set(order) and value['model_buffers'] == {},
        'complete ordered model state and empty original buffer inventory required')
    for name,shape in shapes.items():_tensor(value['model_state'][name],shape)
    _need(value['weights_sha256'] == _digest(value['model_state']),'dynamic model digest differs')
    progress = value['progress'];steps = progress.get('optimizer_steps') if type(progress) is dict else None
    _need(type(progress) is dict and set(progress) == {'optimizer_steps','epochs_completed','row_cursor'}
        and all(type(item) is int for item in progress.values()) and 8 <= steps <= 8+MAX_STEPS
        and progress == {'optimizer_steps':steps,'epochs_completed':steps//2,'row_cursor':steps%2},
        'exact dynamic progress required')
    moments = value['optimizer_state']
    _need(type(moments) is dict and set(moments) == {'schema','parameters'}
        and moments['schema'] == 'named-adam-state/v1' and type(moments['parameters']) is dict
        and set(moments['parameters']) == set(order),'complete named Adam inventory required')
    for name,shape in shapes.items():
        item = moments['parameters'][name]
        _need(type(item) is dict and set(item) == {'step','exp_avg','exp_avg_sq'}
            and type(item['step']) is int and item['step'] == steps,'every Adam step must match actual progress')
        _tensor(item['exp_avg'],shape);_tensor(item['exp_avg_sq'],shape,True)
    _need(value['optimizer_state_sha256'] == _digest(moments),'dynamic Adam digest differs')
    expected_policy = {'name':'Adam','defaults':subject.ADAM_DEFAULTS}
    expected_groups = [{'parameter_names':order,**subject.ADAM_DEFAULTS}]
    _need(_wire(value['optimizer_policy']) == _wire(expected_policy)
        and _wire(value['parameter_groups']) == _wire(expected_groups),
        'exact original Adam defaults and ordered parameter group required')
    return steps


def _validate(value,expected,subject,candidate,implementation,policy):
    _need(_sha(expected) and _digest(value) == expected,'whole offered checkpoint digest differs')
    _need(type(value) is dict,'plain complete checkpoint mapping required')
    if value.get('schema') == subject.SCHEMA:
        info = subject.inspect(value)
        arm = value['arm']
        _need(info['checkpoint_sha256'] == ANCHORS.get(arm) == expected
            and value['progress'] == {'optimizer_steps':8,'epochs_completed':4,'row_cursor':0},
            'only exact qualified legacy step8 anchor accepted')
        return value,None
    _need(type(value) is dict and set(value) == CP_FIELDS and value['schema'] == SCHEMA
        and value['profile'] == PROFILE and _bridge.compatible_implementation(value['implementation'], implementation),
        'closed versioned journal checkpoint and implementation required')
    anchor = value['legacy_anchor'];info = subject.inspect(anchor)
    _need(value['arm'] == anchor['arm'] and info['checkpoint_sha256'] == ANCHORS.get(value['arm'])
        == value['legacy_anchor_sha256'] and anchor['progress']['optimizer_steps'] == 8,
        'exact embedded original legacy step8 anchor required')
    _need(_wire(value['session_policy']) == _wire(policy),'resume must preserve entire original budget and cadence')
    steps = _numeric(value,anchor,subject)
    journal = value['journal'];spent = value['spent_updates']
    _need(type(journal) is list and type(spent) is int and 1 <= spent <= policy['max_steps_from_legacy_anchor']
        and len(journal) == spent == steps-8,'complete bounded ordered journal/progress required')
    previous = value['legacy_anchor_sha256']
    weights,adam = anchor['weights_sha256'],anchor['optimizer_state_sha256']
    for index,entry in enumerate(journal):
        row_index = index%2;row = anchor['population']['rows'][row_index]
        _need(type(entry) is dict and set(entry) == ENTRY_FIELDS
            and entry['schema'] == 'legal-gated-journal-training-transition/v1'
            and type(entry['ordinal']) is int and entry['ordinal'] == index+1
            and type(entry['new_step']) is int and entry['new_step'] == 9+index
            and type(entry['row_index']) is int and entry['row_index'] == row_index
            and entry['row_id'] == row['id'] and entry['row_sha256'] == _digest(row)
            and entry['previous_digest'] == previous and entry['before_weights_sha256'] == weights
            and entry['before_Adam_state_sha256'] == adam,'journal order/row/parent chain differs')
        for key in ('after_weights_sha256','after_Adam_state_sha256','full_sequence_logits_sha256',
            'preclip_gradients_sha256','postclip_gradients_sha256'):
            _need(_sha(entry[key]),'complete journal numerical commitment required')
        _need(type(entry['loss']) is float and math.isfinite(entry['loss'])
            and all(type(entry[key]) is int and entry[key] == 1 for key in
                ('actual_GRUs','actual_backwards','actual_Adam_steps')),'exact completed transition accounting required')
        previous = _digest(entry);weights = entry['after_weights_sha256'];adam = entry['after_Adam_state_sha256']
    _need(value['journal_head_sha256'] == previous and value['weights_sha256'] == weights
        and value['optimizer_state_sha256'] == adam,'journal head must bind full current state')
    counts = value['accounting']
    _need(type(counts) is dict and set(counts) == set(COUNTERS)
        and all(type(item) is int and item >= 0 for item in counts.values()),'complete cumulative physical counts required')
    for key in ('model_forward_entered','model_forward_completed','GRU_entered','GRU_completed',
        'backward_entered','backward_completed','Adam_step_entered','Adam_step_completed'):
        _need(counts[key] == spent,'checkpoint physical steps must preserve all spent transitions')
    restores = counts['model_restore_entered']
    _need(1 <= restores <= 2 and all(counts[key] == restores for key in
        ('model_restore_completed','optimizer_restore_entered','optimizer_restore_completed'))
        and counts['dynamic_state_exports'] == restores+spent,'complete restore/export counts required')
    previous_cp = value['previous_journal_checkpoint_sha256']
    _need(previous_cp is None or _sha(previous_cp),'previous new-profile checkpoint identity differs')
    _need(spent%policy['checkpoint_cadence'] == 0 or spent == policy['max_steps_from_legacy_anchor'],
        'checkpoint must lie on declared cadence or final tail')
    _need(_wire(value['authority']) == _wire(AUTHORITY) and type(value['training_mask']) is int and value['training_mask'] == 0
        and type(value['evaluation_gold_mask']) is int and value['evaluation_gold_mask'] == 0,
        'journal checkpoint grants no semantic eligibility')
    return anchor,value


class PreparedTrainingSession:
    """Opaque process/thread-confined state. No live tensor/model/Adam is returned."""
    __slots__ = ('__dispatch',)
    def __init__(self,dispatch):object.__setattr__(self,'_PreparedTrainingSession__dispatch',dispatch)
    def __setattr__(self,name,value):raise JournalTrainingError('session attributes are private and fixed')
    def __copy__(self):raise JournalTrainingError('live session cannot be copied')
    def __deepcopy__(self,memo):raise JournalTrainingError('live session cannot be copied')
    def __reduce__(self):raise JournalTrainingError('live session cannot be serialized')
    def advance(self,*,steps=1):return self.__dispatch('advance',steps)
    def snapshot_numeric(self):return self.__dispatch('snapshot_numeric',None)
    def checkpoint(self):
        """Detached complete cadence/final checkpoint; durability is external.

        After poison only the last emitted checkpoint can be returned, and only
        if source/runtime/cache fences pass. A still-tampered cache/RNG refuses;
        inspect retains the last identity and failure evidence regardless.
        """
        return self.__dispatch('checkpoint',None)
    def inspect(self):return self.__dispatch('inspect',None)
    def close(self):return self.__dispatch('close',None)
    def __enter__(self):self.inspect();return self
    def __exit__(self,kind,error,traceback):
        try:self.close()
        except BaseException:
            if error is None:raise
            BaseException.add_note(error,'Closing journal training session also failed.')
        return False


def prepare(checkpoint,*,expected_sha,max_steps=3,checkpoint_cadence=2):
    """Validate a legacy anchor/new checkpoint and restore one real model/Adam.

    max_steps is cumulative from original step8, including transitions represented
    by a resumed checkpoint. Durability/physical resource admission are external.
    """
    policy = _policy(max_steps,checkpoint_cadence)
    subject,candidate,implementation = _owners()
    original = _copy(checkpoint,candidate)
    try:anchor,resumed = _validate(original,expected_sha,subject,candidate,implementation,policy)
    except (subject.TrainingStateError,candidate.GatedConditioningError) as error:
        raise JournalTrainingError('original strict legacy anchor validation refused') from error
    _need(resumed is None or resumed['spent_updates'] < max_steps,
        'completed cumulative transition budget cannot allocate a further resume')
    _need(resumed is None or resumed['accounting']['model_restore_completed'] < 2,
        'two actual model/Adam restores exhaust the cumulative closed-profile restore budget')
    anchor_raw = _wire(anchor)
    arm = anchor['arm'];order = list(subject._shapes(arm))
    journal = deepcopy(resumed['journal']) if resumed else []
    counts = deepcopy(resumed['accounting']) if resumed else {key:0 for key in COUNTERS}
    state = {'status':'preparing','busy':False,'stage':'restore','pid':os.getpid(),
        'thread':threading.get_ident(),'model':None,'optimizer':None,'rows':None,'snapshot':None,
        'accounting':counts,'spent_updates':len(journal),'journal':journal,
        'journal_head_sha256':resumed['journal_head_sha256'] if resumed else ANCHORS[arm],
        'numeric_raw':None,'last_checkpoint_raw':_wire(resumed) if resumed else None,
        'last_checkpoint_sha256':expected_sha if resumed else None,
        'previous_checkpoint_sha256':expected_sha if resumed else None,
        'last_failure_stage':None,'partial':None,'timing':{},'hooks':[],
        'checkpoint_after_restore_requires_advance':resumed is not None}

    @contextmanager
    def span(category):
        state['stage'] = category;wall,cpu = time.perf_counter_ns(),time.thread_time_ns()
        try:yield
        finally:
            item = state['timing'].setdefault(category,{'calls':0,'wall_ns':0,'thread_cpu_ns':0})
            item['calls'] += 1;item['wall_ns'] += time.perf_counter_ns()-wall
            item['thread_cpu_ns'] += time.thread_time_ns()-cpu

    def decorate(error):
        result = error if isinstance(error,JournalTrainingError) else JournalTrainingError(
            'journal training failed during '+state['stage']+' ('+type(error).__name__+')')
        result.accounting = deepcopy(counts)
        result.last_failure_stage = state['stage']
        result.completed_updates = state['spent_updates']
        result.last_checkpoint_sha256 = state['last_checkpoint_sha256']
        return result

    try:
        with span('restore'):
            counts['model_restore_entered'] += 1;counts['optimizer_restore_entered'] += 1
            model,optimizer = subject.restore(anchor)
            state['model'],state['optimizer'] = model,optimizer
            counts['model_restore_completed'] += 1;counts['optimizer_restore_completed'] += 1
            numerical = candidate._owners(numerical=True)['numerical'];torch = numerical._torch()
            rng = torch.get_rng_state().clone();runtime = candidate.runtime_metadata()
            if resumed:
                templates = model.state_dict()
                model.load_state_dict({name:numerical._tensor(resumed['model_state'][name],template,name)
                    for name,template in templates.items()},strict=True)
                for name,parameter in model.named_parameters():
                    item = resumed['optimizer_state']['parameters'][name]
                    optimizer.state[parameter] = {
                        'step':torch.tensor(float(item['step']),dtype=torch.float32,device='cpu'),
                        'exp_avg':numerical._tensor(item['exp_avg'],parameter,name+' exp_avg'),
                        'exp_avg_sq':numerical._tensor(item['exp_avg_sq'],parameter,name+' exp_avg_sq',nonnegative=True)}
            model.train()

        def tensor_mark(value):
            _need(isinstance(value,torch.Tensor) and value.device.type == 'cpu'
                and value.layout is torch.strided and value.is_contiguous(),'plain contiguous CPU tensor required')
            body = bytes(value.detach().contiguous().reshape(-1).view(torch.uint8).tolist())
            return (id(value),value.data_ptr(),tuple(value.shape),tuple(value.stride()),value.storage_offset(),
                str(value.dtype),value.requires_grad,value._version,hashlib.sha256(body).hexdigest())

        def numeric_mark():
            named = list(model.named_parameters())
            _need([name for name,_ in named] == order and list(model.state_dict()) == order
                and list(model.named_buffers()) == [] and type(optimizer) is torch.optim.Adam
                and len(optimizer.param_groups) == 1,'original complete private model/Adam inventory differs')
            group = optimizer.param_groups[0]
            _need(len(group['params']) == len(named) and all(a is b for a,(_,b) in zip(group['params'],named))
                and set(optimizer.state) == {parameter for _,parameter in named},'private Adam membership differs')
            moments = []
            for name,parameter in named:
                item = optimizer.state[parameter]
                _need(type(item) is dict and set(item) == {'step','exp_avg','exp_avg_sq'},'closed private named Adam required')
                moments.append((name,tuple((key,tensor_mark(item[key])) for key in sorted(item))))
            return (tuple((name,tensor_mark(parameter),None if parameter.grad is None else tensor_mark(parameter.grad))
                    for name,parameter in named),tuple(moments),
                tuple((name,id(module),type(module),module.training,id(type(module).forward))
                    for name,module in model.named_modules()),_wire(optimizer.defaults),
                _wire({key:item for key,item in group.items() if key != 'params'}))

        def export_numeric(steps):
            with span('dynamic_state_export'):
                weights,moments = subject._export(model,optimizer,arm,steps,torch)
                counts['dynamic_state_exports'] += 1
            return {'schema':NUMERIC_SCHEMA,'arm':arm,'model_state':weights,'weights_sha256':_digest(weights),
                'model_buffers':{},'parameter_order':order,'optimizer_state':moments,
                'optimizer_state_sha256':_digest(moments),
                'optimizer_policy':{'name':'Adam','defaults':deepcopy(subject.ADAM_DEFAULTS)},
                'parameter_groups':[{'parameter_names':order,**deepcopy(subject.ADAM_DEFAULTS)}],
                'progress':{'optimizer_steps':steps,'epochs_completed':steps//2,'row_cursor':steps%2}}

        initial = resumed if resumed else anchor
        numeric = export_numeric(initial['progress']['optimizer_steps'])
        _need(numeric['model_state'] == initial['model_state'] and numeric['optimizer_state'] == initial['optimizer_state'],
            'complete actual model/Adam restore is not exact')
        state['numeric_raw'] = _wire(numeric)
        with span('tensor_cache_preparation'):
            rows = []
            for row in anchor['population']['rows']:
                metadata = {'id':row['id'],'row_sha256':_digest(row),'target_ids':tuple(row['target_ids'])}
                vector = torch.tensor([row['conditioning']],dtype=torch.float32,device='cpu')
                target = torch.tensor([row['target_ids']],dtype=torch.long,device='cpu')
                _need(tuple(vector.shape) == (1,384) and tuple(target.shape) == (1,47)
                    and bool(torch.isfinite(vector).all()),'fixed full384/47-ID cached row required')
                rows.append({'metadata':metadata,'metadata_sha256':_digest(metadata),'tensors':(vector,target),
                    'marks':(tensor_mark(vector),tensor_mark(target))})
            state['rows'] = rows
        decoder = model.body.decoder if arm == 'gated_per_step' else model.decoder
        current_forward = {'active':False,'seen':False}
        def gru_enter(module,args):
            _need(current_forward['active'] and not current_forward['seen'] and len(args) == 2
                and tuple(args[0].shape) == (1,46,8) and tuple(args[1].shape) == (1,1,8),
                'unexpected physical GRU outside one full teacher-forced transition')
            current_forward['seen'] = True;counts['GRU_entered'] += 1
        def gru_complete(module,args,result):
            _need(current_forward['active'] and current_forward['seen'] and type(result) is tuple
                and tuple(result[0].shape) == (1,46,8) and tuple(result[1].shape) == (1,1,8),
                'complete physical GRU geometry differs')
            counts['GRU_completed'] += 1
        state['hooks'] = [decoder.register_forward_pre_hook(gru_enter),decoder.register_forward_hook(gru_complete)]
        state['snapshot'] = numeric_mark()

        def guard(*,check_numeric=True):
            _need(os.getpid() == state['pid'] and threading.get_ident() == state['thread'],
                'session confined to original process and thread')
            with span('source_runtime_fence'):
                observed = _owners()[2]
                _need(observed == implementation,'checked session or original owner changed')
                _need(candidate.runtime_metadata() == runtime == anchor['runtime']
                    and torch.equal(rng,torch.get_rng_state()) and torch.get_default_dtype() is torch.float32
                    and str(torch.get_default_device()) == 'cpu' and torch.is_grad_enabled()
                    and not torch.is_inference_mode_enabled() and not torch.cuda.is_initialized()
                    and not torch.is_autocast_enabled('cpu'),'source runtime/defaults/RNG policy changed')
            with span('cache_state_fence'):
                _need(len(state['rows']) == 2,'complete original cached row inventory required')
                for row in state['rows']:
                    _need(_digest(row['metadata']) == row['metadata_sha256'] and type(row['tensors']) is tuple
                        and len(row['tensors']) == 2 and tuple(tensor_mark(item) for item in row['tensors']) == row['marks'],
                        'cached input bytes/object/shape/dtype/layout changed')
                if check_numeric:_need(numeric_mark() == state['snapshot'],'private model/Adam/gradient/buffer state changed')

        def summary():
            return {'schema':SESSION_SCHEMA,'profile':PROFILE,'status':state['status'],'arm':arm,
                'progress':json.loads(state['numeric_raw'])['progress'],
                'spent_updates':state['spent_updates'],'remaining_updates':max_steps-state['spent_updates'],
                'accounting':deepcopy(counts),'session_policy':deepcopy(policy),
                'journal_head_sha256':state['journal_head_sha256'],
                'last_checkpoint_sha256':state['last_checkpoint_sha256'],
                'last_checkpoint_durability_claimed':False,'last_failure_stage':state['last_failure_stage'],
                'partial_step':deepcopy(state['partial']),'timing':deepcopy(state['timing']),
                'timing_scope':'sequential listed wall/calling-thread CPU phases; caller IO/native and dispatch copying external',
                'actual_GRU_hooks_internal_require_independent_caller_observation':True,
                'legacy_per_step_checkpoint_or_SHA_constructed':False,'authority':deepcopy(AUTHORITY)}

        def gradients():
            result = {}
            for name,parameter in model.named_parameters():
                value = parameter.grad
                _need(value is not None and tuple(value.shape) == tuple(parameter.shape)
                    and value.dtype is torch.float32 and value.device.type == 'cpu'
                    and bool(torch.isfinite(value).all()),'complete finite named gradients required')
                result[name] = value.detach().tolist()
            return result

        def flatten(value):
            if type(value) is list:return [item for child in value for item in flatten(child)]
            _need(type(value) is float and math.isfinite(value),'finite named gradient coordinate required')
            return [value]

        def step():
            guard();before = json.loads(state['numeric_raw'])
            row_index = before['progress']['row_cursor'];cached = state['rows'][row_index]
            vector,target = cached['tensors'];ids = list(cached['metadata']['target_ids'])
            model.train();optimizer.zero_grad(set_to_none=True)
            partial = {'schema':'legal-gated-journal-training-partial-step/v1','status':'entered',
                'arm':arm,'new_step':9+state['spent_updates'],'row_index':row_index,
                'before_numeric_sha256':_digest(before),'target_ids':ids}
            state['partial'] = partial
            current_forward.update(active=True,seen=False)
            try:
                with span('forward'):
                    counts['model_forward_entered'] += 1
                    projected,logits = model(vector,target[:,:-1])
                    counts['model_forward_completed'] += 1
            finally:current_forward['active'] = False
            _need(current_forward['seen'] and tuple(projected.shape) == (1,384)
                and tuple(logits.shape) == (1,46,537) and bool(torch.isfinite(projected).all())
                and bool(torch.isfinite(logits).all()) and logits.requires_grad,'complete finite teacher-forced forward required')
            full_logits = logits.detach().tolist();partial['full_sequence_logits'] = full_logits
            with span('loss'):
                loss = torch.nn.functional.cross_entropy(logits.reshape(-1,537),target[:,1:].reshape(-1),ignore_index=0)
                _need(tuple(loss.shape) == () and bool(torch.isfinite(loss)) and loss.requires_grad,'finite full537 CE required')
            partial['loss'] = float(loss.detach())
            with span('backward'):
                counts['backward_entered'] += 1;loss.backward();counts['backward_completed'] += 1
            with span('gradient_capture_clip'):
                preclip = gradients();coordinates = [x for value in preclip.values() for x in flatten(value)]
                stdlib_norm = math.sqrt(math.fsum(x*x for x in coordinates))
                norm = torch.nn.utils.clip_grad_norm_(list(model.parameters()),5.0,error_if_nonfinite=True)
                factor = float(torch.clamp(5.0/(norm+1e-6),max=1.0).detach());postclip = gradients()
            partial.update(preclip_gradients=preclip,postclip_gradients=postclip,
                preclip_global_L2_Torch=float(norm.detach()),clip_factor=factor)
            with span('Adam'):
                counts['Adam_step_entered'] += 1;optimizer.step();counts['Adam_step_completed'] += 1
            after = export_numeric(before['progress']['optimizer_steps']+1)
            partial.update(actual_after_model_state=after['model_state'],actual_after_Adam_state=after['optimizer_state'])
            entry = {'schema':'legal-gated-journal-training-transition/v1','ordinal':state['spent_updates']+1,
                'new_step':after['progress']['optimizer_steps'],'row_index':row_index,
                'row_id':cached['metadata']['id'],'row_sha256':cached['metadata']['row_sha256'],
                'previous_digest':state['journal_head_sha256'],
                'before_weights_sha256':before['weights_sha256'],'after_weights_sha256':after['weights_sha256'],
                'before_Adam_state_sha256':before['optimizer_state_sha256'],
                'after_Adam_state_sha256':after['optimizer_state_sha256'],
                'full_sequence_logits_sha256':_digest(full_logits),'preclip_gradients_sha256':_digest(preclip),
                'postclip_gradients_sha256':_digest(postclip),'loss':float(loss.detach()),
                'actual_GRUs':1,'actual_backwards':1,'actual_Adam_steps':1}
            with span('journal_commit'):
                state['journal'].append(entry);state['journal_head_sha256'] = _digest(entry)
                state['numeric_raw'] = _wire(after);state['spent_updates'] += 1
                state['checkpoint_after_restore_requires_advance'] = False
                state['snapshot'] = numeric_mark()
            guard()
            report = {'schema':STEP_SCHEMA,'arm':arm,'new_step':after['progress']['optimizer_steps'],
                'row_id':cached['metadata']['id'],'row_index':row_index,'target_ids':ids,
                'offered_ids':ids[:-1],'label_ids':ids[1:],'full_sequence_logits':full_logits,
                'output_shape':[1,46,537],'loss':float(loss.detach()),
                'preclip_gradients':preclip,'postclip_gradients':postclip,
                'preclip_global_L2_stdlib':stdlib_norm,'preclip_global_L2_Torch':float(norm.detach()),
                'clip_factor':factor,'objective':'full537_sequence_cross_entropy','ignore_index':0,'global_clip_L2':5.0,
                'before_numeric_sha256':_digest(before),'after_numeric_sha256':_digest(after),
                'before_model_state_sha256':before['weights_sha256'],'after_model_state_sha256':after['weights_sha256'],
                'before_Adam_state_sha256':before['optimizer_state_sha256'],
                'after_Adam_state_sha256':after['optimizer_state_sha256'],
                'before_progress':before['progress'],'after_progress':after['progress'],
                'journal_entry':deepcopy(entry),'journal_head_sha256':state['journal_head_sha256'],
                'actual_GRUs':1,'actual_backwards':1,'actual_Adam_steps':1,
                'checkpoint_durable':False,'legacy_checkpoint_sha256':None,'training_exposed':True,
                'source_encoder_authenticated':False,'authority':deepcopy(AUTHORITY)}
            _wire(report,MAX_REPORT_BYTES);state['partial'] = None
            return report

        def full_checkpoint():
            spent = state['spent_updates']
            _need(spent > 0 and (spent%checkpoint_cadence == 0 or spent == max_steps),
                'checkpoint only available at declared cadence or final tail')
            if state['last_checkpoint_raw'] is not None:
                previous = json.loads(state['last_checkpoint_raw'])
                if previous['spent_updates'] == spent:return previous
            numeric = json.loads(state['numeric_raw'])
            value = {key:deepcopy(numeric[key]) for key in ('model_state','weights_sha256','model_buffers',
                'parameter_order','optimizer_state','optimizer_state_sha256','optimizer_policy','parameter_groups','progress')}
            value.update(schema=SCHEMA,profile=PROFILE,arm=arm,legacy_anchor=json.loads(anchor_raw),
                legacy_anchor_sha256=ANCHORS[arm],implementation=deepcopy(implementation),session_policy=deepcopy(policy),
                journal=deepcopy(state['journal']),journal_head_sha256=state['journal_head_sha256'],
                spent_updates=spent,accounting=deepcopy(counts),
                previous_journal_checkpoint_sha256=state['previous_checkpoint_sha256'],
                authority=deepcopy(AUTHORITY),training_mask=0,evaluation_gold_mask=0)
            body = _wire(value)
            state['last_checkpoint_raw'] = body
            state['last_checkpoint_sha256'] = hashlib.sha256(body).hexdigest()
            return json.loads(body)

        def dispatch(operation,argument):
            nonlocal model,optimizer,decoder
            _need(os.getpid() == state['pid'] and threading.get_ident() == state['thread'],
                'session confined to original process and thread')
            _need(not state['busy'],'session operations cannot overlap or reenter')
            if operation == 'inspect':return summary()
            if operation == 'close' and state['status'] == 'closed':return summary()
            _need(state['status'] != 'closed','session lifetime ended')
            if operation == 'advance':
                _need(state['status'] == 'ready','failed session cannot advance')
                _need(type(argument) is int and 1 <= argument <= 4
                    and argument <= max_steps-state['spent_updates'],'plain bounded advance within cumulative budget required')
            if operation == 'snapshot_numeric':_need(state['status'] == 'ready','failed session cannot expose live numeric state')
            if operation == 'checkpoint' and state['status'] == 'ready':
                _need(not state['checkpoint_after_restore_requires_advance'],
                    'resumed session must advance before emitting a new checkpoint with current restore accounting')
                _need(state['spent_updates'] > 0 and (state['spent_updates']%checkpoint_cadence == 0
                    or state['spent_updates'] == max_steps),'checkpoint only available at declared cadence or final tail')
            _need(operation in ('advance','snapshot_numeric','checkpoint','close'),'unknown session operation')
            state['busy'] = True
            try:
                if operation == 'close':
                    prior = state['status'];closing_errors = []
                    try:guard(check_numeric=True)
                    except BaseException as error:closing_errors.append(type(error).__name__)
                    finally:
                        for hook in state['hooks']:hook.remove()
                        state['hooks'] = [];state['model'] = state['optimizer'] = state['rows'] = state['snapshot'] = None
                        model = optimizer = decoder = None
                        state['status'] = 'closed'
                    result = summary();result.update(status_before_close=prior,
                        private_references_released=True,closing_guard_passed=not closing_errors,
                        closing_error_types=closing_errors)
                    if closing_errors and prior == 'ready':raise JournalTrainingError('ready session closing integrity check failed')
                    return result
                guard(check_numeric=state['status'] == 'ready')
                if operation == 'snapshot_numeric':return json.loads(state['numeric_raw'])
                if operation == 'checkpoint':
                    if state['status'] == 'poisoned':
                        _need(state['last_checkpoint_raw'] is not None,'no fully emitted checkpoint before failure')
                        return json.loads(state['last_checkpoint_raw'])
                    return full_checkpoint()
                reports = [step() for _ in range(argument)]
                return {'schema':'legal-gated-journal-training-advance/v1','reports':reports,
                    'progress':json.loads(state['numeric_raw'])['progress'],
                    'accounting':deepcopy(counts),'journal_head_sha256':state['journal_head_sha256'],
                    'checkpoint_durability_claimed':False}
            except BaseException as error:
                state['last_failure_stage'] = state['stage']
                if operation != 'close':state['status'] = 'poisoned'
                if isinstance(error,(KeyboardInterrupt,SystemExit)):
                    BaseException.add_note(error,'Observed counters and partial state remain available through inspect().')
                    raise
                raise decorate(error) from error
            finally:state['busy'] = False

        state['status'] = 'ready';guard()
        return PreparedTrainingSession(dispatch)
    except BaseException as error:
        state['last_failure_stage'] = state['stage'];state['status'] = 'poisoned'
        for hook in state['hooks']:hook.remove()
        state['hooks'] = [];state['model'] = state['optimizer'] = state['rows'] = state['snapshot'] = None
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
        raise decorate(error) from error


def source_profile_bridge():
    """Describe this experimental port without loading checkpoints or Torch."""
    _bridge.require_source('journal_session', _PORTED_SOURCE_SHA256)
    return _bridge.profile_bridge('journal_session')
