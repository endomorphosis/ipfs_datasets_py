"""Read-only model-only consumer of the explicit compact384 journal checkpoint.

No training prepare/restore, Adam, backward or target-derived prefix is used.
Pure complete checkpoint validation may inspect embedded historical targets;
the separately pinned serving view contains only conditioning/context/provenance.
The unchanged model builder may retain private historical metadata through its
class closure. This API exposes no model/describe method; target-free refers to
accepted serving inputs, forward arguments, selection and serialized states, not
absolute process-memory invisibility or malicious introspection resistance.
Every scored generation decision calls the current model on its full own prefix.
Serialized continuation validation checks arithmetic and source commitments, not
cryptographic model provenance; actual saved-call custody belongs to the caller.
"""
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import threading

from . import _legacy_source_bridge_v1 as _bridge

_PORTED_SOURCE_SHA256 = _bridge.source_reference('journal_inference')["sha256"]

PROFILE = 'authored-compact384-journal-full-prefix-readonly-bos64-development/v1'
STATE_SCHEMA = 'legal-gated-journal-inference-state/v1'
VIEW_SCHEMA = 'legal-gated-journal-inference-views/v1'
SESSION_SCHEMA = 'legal-gated-journal-inference-session/v1'
MAX_TOKENS = 64
MAX_STATE_BYTES = 8 * 1024**2
JOURNAL_SHA = '527159a86b380e81c376d80e8464aa79420b71ab13e471faa33a3e72442beffc'
PACKET_SHA = 'b44d6d56a99569a78f74c702fac5d9c550a3506d31e39255aa038528816b3894'
ROWS = ('fictional-retention','fictional-inspection')
AUTHORITY = dict.fromkeys(('source_encoder_authenticated','statutory_accuracy','heldout_accuracy',
    'graph_admission','Lean_admission','production_ready','native_admission'),False)
VIEW_FIELDS = {'schema','origin_packet_sha256','rows','training_exposed',
    'source_encoder_authenticated','context_permission_verified'}
ROW_FIELDS = {'id','conditioning','conditioning_sha256','context_utf8','context_sha256','source_sha256','source_group'}
STATE_FIELDS = {'schema','profile','implementation','checkpoint_sha256','views_sha256','row_id','max_new_tokens',
    'initial_prefix_ids','prefix_ids','generated_ids','selected_token_ids','raw_argmax_ids_by_step','trace',
    'emitted_token_count','forced_decisions','branching_decisions','mask_overrides','status','reason',
    'final_prefix_report','final_decoding','training_exposed','heldout','training_mask','evaluation_gold_mask','authority'}
TRACE_FIELDS = {'index','prefix_ids','full_prefix_output_shape','logits','logits_sha256',
    'prefix_report','selection','actual_GRUs','target_prefix_used','grammar_forced','genuine_branch','allowed_count'}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_PUBLIC = {
    'tokens':('legal_compact_content_tokens_v1.py','145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e'),
    'selection':('legal_compact_content_selection_v1.py','936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656'),
}


class JournalInferenceError(ValueError):
    """Profile, serving state, custody, numerical or session lifetime refusal."""


def _need(value,message):
    if not value:raise JournalInferenceError(message)


def _wire(value,maximum=MAX_STATE_BYTES):
    try:body = json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError) as error:
        raise JournalInferenceError('bounded ordinary finite JSON required') from error
    _need(len(body) <= maximum,'complete inference JSON bound exceeded')
    return body


def _digest(value):return hashlib.sha256(_wire(value)).hexdigest()


def _source(path,expected):
    path = Path(path)
    _need(path.is_absolute() and path.resolve(strict=True) == path,'plain absolute source required')
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 1024**2,
        'bounded single-link source required')
    body = path.read_bytes();after = path.lstat()
    mark = lambda row:(row.st_dev,row.st_ino,row.st_mode,row.st_nlink,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
    _need(mark(before) == mark(after) and len(body) == before.st_size
        and hashlib.sha256(body).hexdigest() == expected,'source bytes or physical identity changed')
    return {'path':str(path),'bytes':len(body),'sha256':expected}


def _owners():
    from . import journal_training_session_v1 as journal
    journal_ref = _bridge.require_module("journal_session", journal)
    journal_source = _source(journal.__file__, journal_ref["sha256"])
    subject, candidate, implementation = journal._owners()
    root = Path(candidate._sources()[0]["path"]).parent
    public = {}; pins = []
    for key, (filename, wanted) in _PUBLIC.items():
        path = root / filename
        module = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder." + filename[:-3])
        _need(Path(module.__file__).absolute() == path, "original public grammar/selector origin differs")
        public[key] = module; pins.append(_source(path, wanted))
    return journal, subject, candidate, public, {
        "runtime": _source(_SELF_PATH, _SELF_SHA), "journal_owner": journal_source,
        "journal_implementation": implementation, "public_owners": pins,
        "source_profile_bridge_sha256": _bridge.implementation_sha256()}


def _pure_checkpoint(checkpoint,expected):
    journal,subject,candidate,public,sources = _owners()
    try:
        value = journal._copy(checkpoint,candidate)
        anchor,resumed = journal._validate(value,expected,subject,candidate,
            sources['journal_implementation'],journal._policy(3,2))
    except (journal.JournalTrainingError,subject.TrainingStateError,candidate.GatedConditioningError) as error:
        raise JournalInferenceError('strict complete journal checkpoint validation refused') from error
    _need(resumed is not None and value['schema'] == journal.SCHEMA and value['profile'] == journal.PROFILE
        and value['progress'] == {'optimizer_steps':11,'epochs_completed':5,'row_cursor':1}
        and value['spent_updates'] == 3,'only complete qualified journal step11 profile accepted')
    return value,anchor,journal,subject,candidate,public,sources


def inspect(checkpoint,*,expected_sha):
    """Complete pure source/profile/state inspection without a model or Adam."""
    value,anchor,journal,subject,candidate,public,sources = _pure_checkpoint(checkpoint,expected_sha)
    return {'schema':'legal-gated-journal-inference-checkpoint-inspection/v1','checkpoint_sha256':expected_sha,
        'checkpoint_schema':value['schema'],'checkpoint_profile':value['profile'],'arm':value['arm'],
        'progress':deepcopy(value['progress']),'weights_sha256':value['weights_sha256'],
        'legacy_anchor_sha256':value['legacy_anchor_sha256'],'source_owners':sources,
        'model_allocated':False,'Adam_allocated':False,'historical_targets_excluded_from_serving_inputs':True,
        'historical_target_process_invisibility_claimed':False,
        'authority':deepcopy(AUTHORITY)}


def _views(offered,expected,anchor,journal,candidate):
    try:value = journal._copy(offered,candidate)
    except journal.JournalTrainingError as error:raise JournalInferenceError('bounded target-free serving views required') from error
    _need(type(expected) is str and len(expected) == 64 and _digest(value) == expected
        and type(value) is dict and set(value) == VIEW_FIELDS and value['schema'] == VIEW_SCHEMA
        and value['origin_packet_sha256'] == PACKET_SHA and value['training_exposed'] is True
        and value['source_encoder_authenticated'] is False and value['context_permission_verified'] is False
        and type(value['rows']) is list and all(type(row) is dict for row in value['rows'])
        and [row.get('id') for row in value['rows']] == list(ROWS),
        'closed committed original target-free serving view required')
    for row,original in zip(value['rows'],anchor['population']['rows']):
        _need(type(row) is dict and set(row) == ROW_FIELDS and row['id'] == original['id']
            and row['source_sha256'] == original['source_sha256'] and row['source_group'] == original['source_group']
            and type(row['conditioning']) is list and len(row['conditioning']) == 384
            and all(type(x) is float and math.isfinite(x) and abs(x) <= 1e8 for x in row['conditioning'])
            and _digest(row['conditioning']) == row['conditioning_sha256'] == original['conditioning_sha256']
            and type(row['context_utf8']) is str and 0 < len(row['context_utf8'].encode()) <= 524288
            and hashlib.sha256(row['context_utf8'].encode()).hexdigest() == row['context_sha256'] == original['context_sha256'],
            'serving conditioning/context/provenance differs from exact enrolled original commitments')
    return value


def _options(row,codec,codec_sha):
    return {'expected_context_sha256':row['context_sha256'],'codec':codec,'expected_codec_sha256':codec_sha}


def _status(prefix_report,emitted):
    if prefix_report['status'] == 'complete':return 'complete',None
    if not prefix_report['allowed_token_ids']:return 'blocked',prefix_report['reason'] or prefix_report['status']
    if emitted == MAX_TOKENS:return 'step_budget_exhausted','max_new_tokens_reached'
    return 'continuable',None


def _validate_resume(offered,expected,cp_sha,view_sha,sources,rows,codec,codec_sha,tokens,selection,journal,candidate):
    try:value = journal._copy(offered,candidate)
    except journal.JournalTrainingError as error:raise JournalInferenceError('bounded complete generated continuation state required') from error
    _need(type(expected) is str and len(expected) == 64 and _digest(value) == expected
        and type(value) is dict and set(value) == STATE_FIELDS and value['schema'] == STATE_SCHEMA
        and value['profile'] == PROFILE and _bridge.compatible_implementation(value['implementation'], sources)
        and value['checkpoint_sha256'] == cp_sha and value['views_sha256'] == view_sha
        and value['row_id'] in ROWS and type(value['max_new_tokens']) is int and value['max_new_tokens'] == 64
        and value['initial_prefix_ids'] == [1] and type(value['initial_prefix_ids'][0]) is int,
        'complete source/checkpoint/view-bound generated continuation required; arbitrary prefill refused')
    row = rows[value['row_id']];raw = row['context_utf8'].encode();options = _options(row,codec,codec_sha)
    trace = value['trace'];_need(type(trace) is list and len(trace) <= MAX_TOKENS,'bounded complete decision trace required')
    prefix = [1];chosen = [];raw_max = [];forced = branching = overrides = 0
    for index,item in enumerate(trace):
        _need(type(item) is dict and set(item) == TRACE_FIELDS and type(item['index']) is int
            and item['index'] == index and item['prefix_ids'] == prefix
            and all(type(token) is int for token in item['prefix_ids'])
            and _wire(item['full_prefix_output_shape']) == _wire([1,len(prefix),537])
            and type(item['logits']) is list and len(item['logits']) == 537
            and all(type(score) is float and math.isfinite(score) for score in item['logits'])
            and item['logits_sha256'] == _digest(item['logits']),
            'complete ordered full-prefix537 score trace required')
        public_prefix = tokens.compact_content_allowed_token_ids_v1(prefix,raw,**options)
        _need(public_prefix['status'] != 'complete' and public_prefix['allowed_token_ids'],
            'continuation may not score after terminal or blocked prefix')
        selected = selection.select_compact_content_token_v1(item['logits'],prefix,raw,**options)
        allowed_count = len(public_prefix['allowed_token_ids'])
        expected_fields = {'prefix_report':public_prefix,'selection':selected,'actual_GRUs':1,
            'target_prefix_used':False,'grammar_forced':allowed_count == 1,'genuine_branch':allowed_count > 1,
            'allowed_count':allowed_count}
        _need(all(_wire(item[key]) == _wire(expected_fields[key]) for key in expected_fields),
            'saved score/public grammar/greedy selection or physical-decision flags differ')
        prefix = list(selected['next_prefix_ids']);chosen.append(selected['selected_token_id']);raw_max.append(selected['raw_argmax_token_id'])
        forced += int(allowed_count == 1);branching += int(allowed_count > 1);overrides += int(selected['selection_overrode_raw_argmax'])
    public_prefix = tokens.compact_content_allowed_token_ids_v1(prefix,raw,**options)
    decoded = tokens.decode_compact_content_tokens_v1(prefix,raw,**options)
    status,reason = _status(public_prefix,len(trace))
    expected_fields = {'prefix_ids':prefix,'generated_ids':prefix,'selected_token_ids':chosen,
        'raw_argmax_ids_by_step':raw_max,'emitted_token_count':len(trace),'forced_decisions':forced,
        'branching_decisions':branching,'mask_overrides':overrides,'status':status,'reason':reason,
        'final_prefix_report':public_prefix,'final_decoding':decoded,'training_exposed':True,'heldout':False,
        'training_mask':0,'evaluation_gold_mask':0,'authority':AUTHORITY}
    _need(all(_wire(value[key]) == _wire(expected_fields[key]) for key in expected_fields),
        'whole generated prefix/counts/terminal parser/authority disagree with complete trace')
    _need((status == 'complete') == (decoded['status'] == 'valid_candidate'),
        'typed complete parser intake required; EOS alone insufficient')
    return value


class JournalInferenceSession:
    __slots__ = ('__dispatch',)
    def __init__(self,dispatch):object.__setattr__(self,'_JournalInferenceSession__dispatch',dispatch)
    def __setattr__(self,name,value):raise JournalInferenceError('readonly session attributes are private and fixed')
    def __copy__(self):raise JournalInferenceError('live inference session cannot be copied')
    def __deepcopy__(self,memo):raise JournalInferenceError('live inference session cannot be copied')
    def __reduce__(self):raise JournalInferenceError('live inference session cannot be serialized')
    def score(self,row_id):return self.__dispatch('score',row_id,None)
    def score_bos(self,row_id):return self.__dispatch('score',row_id,None)
    def advance(self,row_id,*,steps=32):return self.__dispatch('advance',row_id,steps)
    def generate(self,row_id):return self.__dispatch('generate',row_id,None)
    def snapshot_state(self,row_id):return self.__dispatch('snapshot_state',row_id,None)
    def inspect(self):return self.__dispatch('inspect',None,None)
    def close(self):return self.__dispatch('close',None,None)


def prepare(checkpoint,*,expected_sha,views,expected_views_sha,max_new_tokens=64,
            resume_state=None,expected_resume_sha=None):
    """Restore one model only, after complete pure checkpoint/view/trace checks.

    No externally supplied prefix/target/labels are accepted. A resumed trace is
    validated without model replay; its actual model-call provenance is external.
    """
    _need(type(max_new_tokens) is int and max_new_tokens == 64,'exact original64-token BOS allowance required')
    _need((resume_state is None) == (expected_resume_sha is None),'resume state and exact state digest must be supplied together')
    value,anchor,journal,subject,candidate,public,sources = _pure_checkpoint(checkpoint,expected_sha)
    serving = _views(views,expected_views_sha,anchor,journal,candidate)
    tokens,selection = public['tokens'],public['selection']
    codec,codec_sha = deepcopy(anchor['codec']),anchor['codec_sha256']
    rows_meta = {row['id']:deepcopy(row) for row in serving['rows']}
    resumed = None
    if resume_state is not None:
        resumed = _validate_resume(resume_state,expected_resume_sha,expected_sha,expected_views_sha,sources,
            rows_meta,codec,codec_sha,tokens,selection,journal,candidate)
    arm,weights,expected_weights,runtime = value['arm'],deepcopy(value['model_state']),value['weights_sha256'],deepcopy(anchor['runtime'])
    migration = deepcopy(anchor['initial_migration'])
    progress = deepcopy(value['progress']);legacy_anchor_sha = value['legacy_anchor_sha256']
    # Do not copy historical checkpoint targets into serving inputs or states.
    # The unchanged model builder can still retain private parent metadata.
    del value,anchor,serving
    state = {'status':'preparing','busy':False,'model':None,'rows':None,'snapshot':None,'states':{},
        'states_digest':None,'pid':os.getpid(),'thread':threading.get_ident(),'stage':'model_restore',
        'counts':{name:0 for name in ('model_restore_entered','model_restore_completed','model_forward_entered',
            'model_forward_completed','GRU_entered','GRU_completed','score_calls','generated_steps')},
        'historical_generated_steps':0 if resumed is None else resumed['emitted_token_count'],
        'score_rows':set(),'hooks':[],'last_failure_stage':None,'pending_forward':None}
    counts = state['counts'];model = decoder = torch = None

    def decorate(error):
        result = error if isinstance(error,JournalInferenceError) else JournalInferenceError(
            'journal inference failed during '+state['stage']+' ('+type(error).__name__+')')
        result.counts = deepcopy(counts);result.failure_stage = state['stage']
        result.partial_report = {'states':deepcopy(state['states']),'pending_forward':deepcopy(state['pending_forward']),
            'counts':deepcopy(counts),'historical_generated_steps':state['historical_generated_steps']}
        return result

    try:
        numerical = candidate._owners(numerical=True)['numerical'];torch = numerical._torch()
        rng = torch.get_rng_state().clone()
        _need(candidate.runtime_metadata() == runtime,'live CPU runtime differs from exact journal anchor')
        counts['model_restore_entered'] += 1
        wrapped = candidate.restore(migration)
        model = wrapped.body if arm == 'h0_only' else wrapped
        templates = model.state_dict()
        _need(list(templates) == list(subject._shapes(arm)),'complete restored model inventory differs')
        model.load_state_dict({name:numerical._tensor(weights[name],template,name)
            for name,template in templates.items()},strict=True)
        model.eval();state['model'] = model;counts['model_restore_completed'] += 1
        _need(_digest({name:tensor.detach().tolist() for name,tensor in model.state_dict().items()}) == expected_weights,
            'restored full current journal model differs')
        del weights,migration,wrapped

        def mark(tensor):
            _need(isinstance(tensor,torch.Tensor) and tensor.device.type == 'cpu'
                and tensor.layout is torch.strided and tensor.is_contiguous(),'plain contiguous CPU tensor required')
            body = bytes(tensor.detach().contiguous().reshape(-1).view(torch.uint8).tolist())
            return (id(tensor),tensor.data_ptr(),tuple(tensor.shape),tuple(tensor.stride()),tensor.storage_offset(),
                str(tensor.dtype),tensor.requires_grad,tensor._version,hashlib.sha256(body).hexdigest())

        def model_mark():
            return (tuple((name,mark(tensor),None if tensor.grad is None else mark(tensor.grad))
                for name,tensor in model.named_parameters()),
                tuple((name,mark(tensor)) for name,tensor in model.named_buffers()),
                tuple((name,id(module),type(module),module.training,id(type(module).forward))
                    for name,module in model.named_modules()))

        rows = {}
        for row_id,row in rows_meta.items():
            vector = torch.tensor([row['conditioning']],dtype=torch.float32,device='cpu')
            rows[row_id] = {'metadata':deepcopy(row),'metadata_sha256':_digest(row),
                'vector':vector,'mark':mark(vector)}
        state['rows'] = rows;state['snapshot'] = model_mark()
        decoder = model.body.decoder if arm == 'gated_per_step' else model.decoder
        _need(type(decoder) is torch.nn.GRU and sum(type(module) is torch.nn.GRU for module in model.modules()) == 1,
            'one exact inherited GRU required')
        active = {'prefix':None,'seen':False,'completed':False}
        def pre_hook(module,args):
            _need(active['prefix'] is not None and not active['seen'] and len(args) == 2
                and tuple(args[0].shape) == (1,len(active['prefix']),8) and tuple(args[1].shape) == (1,1,8),
                'unexpected physical full-prefix GRU')
            active['seen'] = True;counts['GRU_entered'] += 1
        def post_hook(module,args,result):
            _need(active['seen'] and not active['completed'] and type(result) is tuple
                and tuple(result[0].shape) == (1,len(active['prefix']),8) and tuple(result[1].shape) == (1,1,8),
                'complete physical full-prefix GRU geometry differs')
            active['completed'] = True;counts['GRU_completed'] += 1
        state['hooks'] = [decoder.register_forward_pre_hook(pre_hook),decoder.register_forward_hook(post_hook)]

        def options(row_id):return _options(rows[row_id]['metadata'],codec,codec_sha)
        def refresh(row_id):
            current = state['states'][row_id];row = rows[row_id]['metadata'];raw = row['context_utf8'].encode()
            prefix_report = tokens.compact_content_allowed_token_ids_v1(current['prefix_ids'],raw,**options(row_id))
            decoded = tokens.decode_compact_content_tokens_v1(current['prefix_ids'],raw,**options(row_id))
            status,reason = _status(prefix_report,current['emitted_token_count'])
            _need((status == 'complete') == (decoded['status'] == 'valid_candidate'),
                'whole typed parser completion differs; EOS alone insufficient')
            current.update(status=status,reason=reason,final_prefix_report=prefix_report,final_decoding=decoded)
            state['states_digest'] = _digest(state['states'])
        for row_id in ROWS:
            state['states'][row_id] = {'schema':STATE_SCHEMA,'profile':PROFILE,'implementation':deepcopy(sources),
                'checkpoint_sha256':expected_sha,'views_sha256':expected_views_sha,'row_id':row_id,'max_new_tokens':64,
                'initial_prefix_ids':[1],'prefix_ids':[1],'generated_ids':[1],'selected_token_ids':[],
                'raw_argmax_ids_by_step':[],'trace':[],'emitted_token_count':0,'forced_decisions':0,
                'branching_decisions':0,'mask_overrides':0,'status':'continuable','reason':None,
                'final_prefix_report':None,'final_decoding':None,'training_exposed':True,'heldout':False,
                'training_mask':0,'evaluation_gold_mask':0,'authority':deepcopy(AUTHORITY)}
            refresh(row_id)
        if resumed is not None:
            state['states'][resumed['row_id']] = deepcopy(resumed)
            state['states_digest'] = _digest(state['states'])

        def guard():
            _need(os.getpid() == state['pid'] and threading.get_ident() == state['thread'],
                'inference session confined to original process and thread')
            _need(_wire(_owners()[4]) == _wire(sources),'checked inference/journal/public source owners changed')
            _need(candidate.runtime_metadata() == runtime and torch.equal(rng,torch.get_rng_state())
                and torch.get_default_dtype() is torch.float32 and str(torch.get_default_device()) == 'cpu'
                and not torch.cuda.is_initialized() and not torch.is_autocast_enabled('cpu'),
                'readonly inference runtime/RNG policy changed')
            _need(all(module.training is False for module in model.modules()) and model_mark() == state['snapshot'],
                'readonly model/gradient/buffer/module inventory or bytes changed')
            _need(tuple(rows) == ROWS and state['rows'] is rows,'private serving row inventory changed')
            for row in rows.values():
                _need(_digest(row['metadata']) == row['metadata_sha256'] and mark(row['vector']) == row['mark'],
                    'private serving view/vector bytes/object/geometry changed')
            _need(_digest(state['states']) == state['states_digest'],'private generated prefix/trace state changed')

        def forward(row_id,prefix,kind):
            guard();state['stage'] = kind+'/full_prefix_forward'
            _need(type(prefix) is list and prefix and all(type(token) is int for token in prefix)
                and len(prefix) <= 64,'complete bounded original/generated prefix required')
            active.update(prefix=list(prefix),seen=False,completed=False)
            state['pending_forward'] = {'row_id':row_id,'prefix_ids':list(prefix),'status':'entered',
                'full_prefix_logits':None,'output_shape':None}
            try:
                with torch.inference_mode():
                    offered = torch.tensor([prefix],dtype=torch.long,device='cpu')
                    counts['model_forward_entered'] += 1
                    projected,logits = model(rows[row_id]['vector'],offered)
                    counts['model_forward_completed'] += 1
                    finite = bool(torch.isfinite(logits).all())
                    pending = logits.detach().tolist() if finite else {
                        'encoding':'complete_native_tensor_bytes_hex','shape':list(logits.shape),'dtype':str(logits.dtype),
                        'bytes_hex':bytes(logits.detach().contiguous().reshape(-1).view(torch.uint8).tolist()).hex()}
                    state['pending_forward'].update(status='returned',output_shape=list(logits.shape),full_prefix_logits=pending)
                    _need(tuple(projected.shape) == (1,384) and tuple(logits.shape) == (1,len(prefix),537)
                        and finite and bool(torch.isfinite(projected).all()),'finite complete537 full-prefix output required')
                    scores = logits[0,-1].detach().tolist();projected_values = projected.detach().tolist()
                _need(active['seen'] and active['completed'] and len(scores) == 537
                    and all(type(score) is float and math.isfinite(score) for score in scores),
                    'one actual GRU and all537 finite raw scores required')
            finally:active['prefix'] = None
            # Keep the full actual output until public selection/trace commit.
            # A parser/selector/closing refusal must not discard scored work.
            guard()
            return scores,projected_values

        def summary():
            return {'schema':SESSION_SCHEMA,'profile':PROFILE,'status':state['status'],'arm':arm,
                'checkpoint_sha256':expected_sha,'checkpoint_progress':progress,'weights_sha256':expected_weights,
                'legacy_anchor_sha256':legacy_anchor_sha,'views_sha256':expected_views_sha,
                'counts':deepcopy(counts),'historical_generated_steps':state['historical_generated_steps'],
                'states':deepcopy(state['states']),'last_failure_stage':state['last_failure_stage'],
                'pending_forward':deepcopy(state['pending_forward']),'source_owners':deepcopy(sources),
                'optimizer_allocated_or_executed':False,'training_or_backward_executed':False,
                'target_prefix_accepted':False,'actual_saved_call_provenance_owned_by_caller':True,
                'authority':deepcopy(AUTHORITY)}

        def advance(row_id,limit):
            current = state['states'][row_id];before_models = counts['model_forward_completed'];before_grus = counts['GRU_completed']
            row = rows[row_id]['metadata'];raw = row['context_utf8'].encode()
            for _ in range(limit):
                guard();refresh(row_id)
                if current['status'] != 'continuable':break
                prefix = list(current['prefix_ids']);prefix_report = current['final_prefix_report']
                scores,_ = forward(row_id,prefix,'generation')
                selected = selection.select_compact_content_token_v1(scores,prefix,raw,**options(row_id))
                _need(_wire(selected['prefix_report']) == _wire(prefix_report)
                    and _wire(selected['logits']) == _wire(scores) and selected['logits_sha256'] == _digest(scores)
                    and selected['selection_performed'] is True,'public greedy selector differs from actual raw scores')
                allowed = len(prefix_report['allowed_token_ids'])
                current['trace'].append({'index':current['emitted_token_count'],'prefix_ids':prefix,
                    'full_prefix_output_shape':[1,len(prefix),537],'logits':scores,'logits_sha256':_digest(scores),
                    'prefix_report':deepcopy(prefix_report),'selection':selected,'actual_GRUs':1,'target_prefix_used':False,
                    'grammar_forced':allowed == 1,'genuine_branch':allowed > 1,'allowed_count':allowed})
                current['selected_token_ids'].append(selected['selected_token_id'])
                current['raw_argmax_ids_by_step'].append(selected['raw_argmax_token_id'])
                current['prefix_ids'] = list(selected['next_prefix_ids']);current['generated_ids'] = list(current['prefix_ids'])
                current['emitted_token_count'] += 1;current['forced_decisions'] += int(allowed == 1)
                current['branching_decisions'] += int(allowed > 1)
                current['mask_overrides'] += int(selected['selection_overrode_raw_argmax']);counts['generated_steps'] += 1
                refresh(row_id);_wire(current);guard();state['pending_forward'] = None
            return {'state':deepcopy(current),'new_model_calls':counts['model_forward_completed']-before_models,
                'new_GRUs':counts['GRU_completed']-before_grus,'session_counts':deepcopy(counts)}

        def dispatch(operation,row_id,argument):
            nonlocal model,decoder,rows
            _need(os.getpid() == state['pid'] and threading.get_ident() == state['thread'],
                'inference session confined to original process and thread')
            _need(not state['busy'],'inference operations cannot overlap or reenter')
            if operation == 'inspect':return summary()
            if operation == 'close' and state['status'] == 'closed':return summary()
            _need(state['status'] != 'closed','inference session lifetime ended')
            _need(operation in ('score','advance','generate','snapshot_state','close'),'unknown inference operation')
            if operation != 'close':
                _need(state['status'] == 'ready','poisoned inference session cannot dispatch')
                _need(type(row_id) is str and row_id in ROWS,'exact serving row identifier required')
            if operation == 'score':_need(row_id not in state['score_rows'],'one fixedBOS score observation per row/session')
            if operation == 'advance':
                _need(type(argument) is int and 1 <= argument <= MAX_TOKENS
                    and argument <= MAX_TOKENS-state['states'][row_id]['emitted_token_count'],
                    'plain bounded advance within original64-token allowance required')
            state['busy'] = True
            try:
                if operation == 'close':
                    prior = state['status'];errors = []
                    try:guard()
                    except BaseException as error:errors.append(type(error).__name__)
                    finally:
                        for hook in state['hooks']:hook.remove()
                        state['hooks'] = [];state['model'] = state['rows'] = state['snapshot'] = None
                        model = decoder = rows = None;state['status'] = 'closed'
                    result = summary();result.update(status_before_close=prior,private_references_released=True,
                        closing_guard_passed=not errors,closing_error_types=errors)
                    if errors and prior == 'ready':raise JournalInferenceError('ready inference closing custody failed')
                    return result
                guard()
                if operation == 'snapshot_state':return deepcopy(state['states'][row_id])
                if operation == 'score':
                    scores,projected = forward(row_id,[1],'BOS_score');row = rows[row_id]['metadata'];raw = row['context_utf8'].encode()
                    prefix_report = tokens.compact_content_allowed_token_ids_v1([1],raw,**options(row_id))
                    selected = selection.select_compact_content_token_v1(scores,[1],raw,**options(row_id))
                    state['score_rows'].add(row_id);counts['score_calls'] += 1;guard()
                    state['pending_forward'] = None
                    return {'schema':'legal-gated-journal-inference-bos-score/v1','row_id':row_id,'prefix_ids':[1],
                        'logits':scores,'logits_sha256':_digest(scores),'projected':projected,
                        'full_prefix_output_shape':[1,1,537],'prefix_report':prefix_report,'selection':selected,
                        'actual_GRUs':1,'checkpoint_sha256':expected_sha,'views_sha256':expected_views_sha,
                        'generated_state_advanced':False,'state_unchanged':True,'RNG_unchanged':True,
                        'target_prefix_used':False,'authority':deepcopy(AUTHORITY)}
                remaining = MAX_TOKENS-state['states'][row_id]['emitted_token_count']
                limit = remaining if operation == 'generate' else argument
                return advance(row_id,limit)
            except BaseException as error:
                state['last_failure_stage'] = state['stage']
                if operation != 'close':state['status'] = 'poisoned'
                if isinstance(error,(KeyboardInterrupt,SystemExit)):
                    BaseException.add_note(error,'Readonly inference counters and partial trace remain available through inspect().')
                    raise
                raise decorate(error) from error
            finally:state['busy'] = False

        state['status'] = 'ready';guard()
        return JournalInferenceSession(dispatch)
    except BaseException as error:
        state['last_failure_stage'] = state['stage'];state['status'] = 'poisoned'
        for hook in state['hooks']:hook.remove()
        state['hooks'] = [];state['model'] = state['rows'] = state['snapshot'] = None
        model = decoder = None
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
        raise decorate(error) from error


def source_profile_bridge():
    """Describe this experimental port without loading checkpoints or Torch."""
    _bridge.require_source('journal_inference', _PORTED_SOURCE_SHA256)
    return _bridge.profile_bridge('journal_inference')
