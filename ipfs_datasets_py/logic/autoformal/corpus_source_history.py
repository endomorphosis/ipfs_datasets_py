"""Regenerate bounded candidate snapshot histories; retain unresolved forks.

Genesis uses the unchanged application owner. Each subsequent node replays
original evidence once and authenticates a fixed revision domain. Historical
activation never supplies current authority, physical source facts or legal gold.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_parent_occurrence_adapter as base
from . import corpus_source_adjudication as adjudication
from . import corpus_source_application as application
from . import corpus_source_review as source
from . import corpus_source_review_responses as responses

PROFILE = 'regenerated-candidate-source-snapshot-history/v1'
REVISION_PROFILE = 'signed-candidate-source-answer-revision/v1'
DECLARATION_SCHEMA = 'legal-corpus-source-revision-declaration/v1'
CLAIM_SCHEMA = 'legal-corpus-source-revision-signed-claim/v1'
ACTION = 'revise_candidate_source_answer_snapshot/v1'
AUDIENCE = 'legal-autoformalization-candidate-source-history/v1'
ASSESSMENT_SCHEMA = 'legal-corpus-source-revision-authority-assessment/v1'
REVISION_GROUP_SCHEMA = 'legal-corpus-source-revision-group/v1'
REVISION_MANIFEST_SCHEMA = 'legal-corpus-source-revision-manifest/v1'
REVISION_PAGE_SCHEMA = 'legal-corpus-source-revision-page/v1'
MANIFEST_SCHEMA = 'legal-corpus-source-history-manifest/v1'
GROUP_SCHEMA = 'legal-corpus-source-history-group/v1'
PAGE_SCHEMA = 'legal-corpus-source-history-page/v1'
EPOCH_SCHEMA = 'legal-corpus-source-history-epoch/v1'
EPOCH_PAGE_SCHEMA = 'legal-corpus-source-history-epoch-page/v1'
COMPONENTS = ('manifest', 'pages', 'records', 'epoch_manifests', 'epoch_pages')
FALSE_FLAGS = {**application.FALSE_FLAGS, 'authoritative_history_head_qualified':False,
    'fork_resolution_applied':False, 'global_history_complete_verified':False,
    'evaluation_clock_authenticated':False, 'historical_activation_confers_current_eligibility':False,
    'source_preparation_migration_applied':False, 'downstream_cross_generation_invalidation_qualified':False}
COMMON_FIELDS = {'view', *FALSE_FLAGS, *base.UNSELECTED}
DEFAULT_LIMITS = {'max_epochs':4, 'max_total_groups':32768, 'max_pages':512,
    'max_groups_per_page':64, 'max_page_bytes':contracts.MAX_RECORD_BYTES,
    'max_collection_bytes':64*1024**2, 'max_all_input_bytes':512*1024**2,
    'max_all_input_nodes':8_000_000, 'max_input_depth':64, 'max_all_signed_evidence_bytes':64*1024**2}
DECLARATION_FIELDS = (application.DECLARATION_FIELDS - application.COMMON_FIELDS) | {
    'epoch_id', 'previous_snapshot_group_ref', 'previous_snapshot_manifest_ref', *COMMON_FIELDS}
REVISION_GROUP_FIELDS = (application.GROUP_FIELDS - application.COMMON_FIELDS) | {'previous_snapshot_group_ref', *COMMON_FIELDS}
REVISION_MANIFEST_FIELDS = (application.MANIFEST_FIELDS - application.COMMON_FIELDS) | {'epoch_id', *COMMON_FIELDS}
REVISION_PAGE_FIELDS = (application.PAGE_FIELDS - application.COMMON_FIELDS) | COMMON_FIELDS
GROUP_FIELDS = {'epoch_id', 'generation', 'queue_ordinal', 'request_cid', 'snapshot_manifest_ref',
    'previous_snapshot_manifest_ref', 'snapshot_group_record', 'regenerated_at_explicit_epoch_trust_and_time',
    'current_candidate_refs_eligible_under_selected_history_profile', 'current_eligibility_blockers',
    'current_active_answer_variant_refs', *COMMON_FIELDS}
MANIFEST_FIELDS = {'profile', 'limits', 'genesis_epoch_id', 'snapshot_id', 'use_scope',
    'preparation_manifest_sha256', 'current_epoch_id', 'evaluation_time_utc', 'epoch_refs', 'leaf_epoch_ids',
    'fork_parent_manifest_refs', 'revision_step_pins', 'producer_pins', 'page_refs', 'counts',
    'population_complete_for_supplied_history', *COMMON_FIELDS}
PAGE_FIELDS = {'page_ordinal', 'first_group_ordinal', 'entries', *COMMON_FIELDS}
EPOCH_FIELDS = {'epoch_id', 'kind', 'generation', 'previous_epoch_id', 'snapshot_manifest_record', *COMMON_FIELDS}
EPOCH_PAGE_FIELDS = {'epoch_id', 'page_ordinal', 'snapshot_page_record', *COMMON_FIELDS}
GENESIS_REQUIRED = {'adjudication_report', 'application_registry', 'application_policy', 'application_groups', 'descriptor',
    'expected_adjudication_manifest_sha256', 'expected_application_registry_sha256', 'expected_application_policy_sha256',
    'expected_application_group_pins', 'adjudication_replay_inputs'}
STEP_REQUIRED = {'epoch_id', 'adjudication_report', 'revision_registry', 'revision_policy', 'revision_groups', 'descriptor',
    'expected_adjudication_manifest_sha256', 'expected_revision_registry_sha256', 'expected_revision_policy_sha256',
    'expected_revision_group_pins', 'adjudication_replay_inputs'}
STEP_PIN_FIELDS = {'epoch_id', 'descriptor_sha256', 'adjudication_manifest_sha256', 'registry_sha256',
    'policy_sha256', 'group_pins_sha256', 'evaluation_time_utc'}
REVISION_GROUP_INPUT_FIELDS = (application.GROUP_INPUT_FIELDS - {'app_artifact_id'}) | {'revision_artifact_id'}
REVISION_GROUP_PIN_FIELDS = (application.GROUP_PIN_FIELDS - {'app_artifact_id'}) | {'revision_artifact_id'}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(base._plain(value, contracts.MAX_RECORD_BYTES))


def _ref(value):
    return {'record_cid':value['record_cid'], 'sha256':_digest(value), 'schema':value['schema']}


def _seal(schema, **values):
    payload = {'schema':schema, **values, 'view':'candidate', **FALSE_FLAGS, **base.UNSELECTED}
    base._plain(payload, contracts.MAX_RECORD_BYTES)
    return contracts.seal_record(payload)


def _pins():
    result = application._pins()
    result[str(Path(__file__).resolve())] = _sha(Path(__file__).read_bytes())
    return result


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail('closed lower-only source history limits required')
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        if key not in result or type(bound) is not int or not 0 < bound <= result[key]:
            _fail('unknown or raised source history limit')
        result[key] = bound
    return result


def _reference(value, label):
    contracts.require_keys(value, {'record_cid','sha256','schema'}, label)
    contracts.require_cid(value['record_cid'], label+' DAG-JSON CID', codecs=('dag-json',))
    contracts.require_sha256(value['sha256'], label+' FULL canonical SHA256')
    if value['schema'] not in (application.MANIFEST_SCHEMA, REVISION_MANIFEST_SCHEMA):
        _fail('fixed genesis or revision snapshot manifest schema required')
    return value


def _parent(manifest, group):
    if type(manifest) is not dict:
        _fail('complete bounded predecessor manifest required')
    if manifest.get('schema') == application.MANIFEST_SCHEMA:
        manifest_fields, group_schema, group_fields = application.MANIFEST_FIELDS, application.GROUP_SCHEMA, application.GROUP_FIELDS
    elif manifest.get('schema') == REVISION_MANIFEST_SCHEMA:
        manifest_fields, group_schema, group_fields = REVISION_MANIFEST_FIELDS, REVISION_GROUP_SCHEMA, REVISION_GROUP_FIELDS
    else:
        _fail('fixed genesis or revision predecessor required')
    manifest = contracts.validate_record(base._load(base._plain(manifest, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES),
        schema=manifest['schema'], fields=manifest_fields)
    group = contracts.validate_record(base._load(base._plain(group, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES),
        schema=group_schema, fields=group_fields)
    return manifest, group


def _descriptor(value, parent):
    value = base._load(base._plain(value, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES)
    contracts.require_keys(value, application.DESCRIPTOR_FIELDS, 'closed exact revision descriptor')
    from . import legal_graph_review as auth
    auth._id(value['snapshot_id'], 'candidate revision snapshot ID')
    _reference(value['previous_snapshot_manifest_ref'], 'exact predecessor snapshot reference')
    previous = parent['snapshot_descriptor']
    if (value['snapshot_id'] != previous['snapshot_id'] or value['use_scope'] != application.USE_SCOPE
            or value['use_scope'] != previous['use_scope'] or type(value['generation']) is not int
            or value['generation'] != previous['generation']+1 or value['previous_snapshot_manifest_ref'] != _ref(parent)):
        _fail('revision must preserve snapshot/use and bind exact immediate predecessor generation')
    return value


def record_source_revision_declaration(request, subject, adjudication_group, previous_snapshot_group,
        previous_snapshot_manifest, descriptor, *, epoch_id, expected_request_sha256, expected_subject_sha256,
        expected_adjudication_group_sha256, expected_previous_snapshot_group_sha256, expected_previous_snapshot_manifest_sha256,
        expected_preparation_manifest_sha256, expected_typed_response_manifest_sha256, expected_adjudication_manifest_sha256,
        declared_at_utc, rationale, evidence_refs, limits=None):
    """Author fresh revision intent; predecessor structure supplies no authority."""
    bounds = application._limits(limits)
    from . import legal_graph_review as auth
    auth._id(epoch_id, 'explicit revision epoch ID')
    for digest in (expected_previous_snapshot_group_sha256, expected_previous_snapshot_manifest_sha256):
        contracts.require_sha256(digest, 'independently pinned predecessor FULL SHA256')
    parent, prior_group = _parent(previous_snapshot_manifest, previous_snapshot_group)
    descriptor = _descriptor(descriptor, parent)
    if _digest(parent) != expected_previous_snapshot_manifest_sha256 or _digest(prior_group) != expected_previous_snapshot_group_sha256:
        _fail('independent predecessor snapshot root/group differs')
    base_descriptor = {**descriptor, 'generation':1, 'previous_snapshot_manifest_ref':None}
    common = application.record_source_application_declaration(request, subject, adjudication_group, base_descriptor,
        expected_request_sha256=expected_request_sha256, expected_subject_sha256=expected_subject_sha256,
        expected_adjudication_group_sha256=expected_adjudication_group_sha256,
        expected_preparation_manifest_sha256=expected_preparation_manifest_sha256,
        expected_typed_response_manifest_sha256=expected_typed_response_manifest_sha256,
        expected_adjudication_manifest_sha256=expected_adjudication_manifest_sha256,
        declared_at_utc=declared_at_utc, rationale=rationale, evidence_refs=evidence_refs, limits=bounds)
    if (parent['preparation_manifest_sha256'] != expected_preparation_manifest_sha256
            or prior_group['request_cid'] != request['record_cid'] or prior_group['queue_ordinal'] != request['queue_ordinal']):
        _fail('preparation/population migration cannot be a source-answer revision')
    values = {key:value for key,value in common.items() if key not in {'schema','record_cid','cid_scope',*application.COMMON_FIELDS}}
    values.update(profile=REVISION_PROFILE, snapshot_descriptor=descriptor, epoch_id=epoch_id,
        previous_snapshot_group_ref=_ref(prior_group), previous_snapshot_manifest_ref=_ref(parent),
        status='declared_unauthenticated_candidate_source_revision')
    record = _seal(DECLARATION_SCHEMA, **values)
    base._plain(record, bounds['max_declaration_bytes'])
    return record


def validate_source_revision_declaration(record, *args, **kwargs):
    bounds = application._limits(kwargs.get('limits'))
    checked = contracts.validate_record(base._load(base._plain(record, bounds['max_declaration_bytes']), bounds['max_declaration_bytes']),
        schema=DECLARATION_SCHEMA, fields=DECLARATION_FIELDS)
    expected = record_source_revision_declaration(*args, **kwargs)
    if canonical_dag_json_bytes(checked) != canonical_dag_json_bytes(expected):
        _fail('source revision body differs from exact declared inputs')
    return checked


def _clone(value, bounds):
    """Detach the complete native input tree and charge logical occurrences first."""
    nodes, charged, active = 0, 0, set()
    def visit(item, depth):
        nonlocal nodes, charged
        nodes += 1
        if nodes > bounds['max_all_input_nodes'] or depth > bounds['max_input_depth']:
            _fail('complete history input node/depth bound exceeded before hashing')
        kind = type(item)
        if kind in (dict,list):
            identity = id(item)
            if identity in active:
                _fail('cyclic source history input cannot be detached')
            active.add(identity)
            charged += 2+max(0,len(item)-1)
            if kind is dict:
                result = {}
                for key, child in item.items():
                    if type(key) is not str:
                        _fail('native source history JSON object keys must be strings')
                    charged += len(base._plain(key, max(1,bounds['max_all_input_bytes']-charged)))+1
                    result[key] = visit(child,depth+1)
            else:
                result = [visit(child,depth+1) for child in item]
            active.remove(identity)
        elif kind is bytes:
            charged += len(item)
            result = item
        elif item is None or kind in (str,int,bool,float):
            charged += len(base._plain(item,max(1,bounds['max_all_input_bytes']-charged)))
            result = item
        else:
            _fail('closed native history values required; no callback or custom loader')
        if charged > bounds['max_all_input_bytes']:
            _fail('complete history input byte budget exceeded before hashing')
        return result
    result = visit(value,0)
    return result, {'logical_input_bytes':charged,'native_input_nodes':nodes}


def _project(groups, pins):
    projected, projected_pins = [], []
    for values, fields, output in ((groups,REVISION_GROUP_INPUT_FIELDS,projected), (pins,REVISION_GROUP_PIN_FIELDS,projected_pins)):
        if type(values) is not list:
            _fail('complete ordered revision groups/pins required')
        for row in values:
            contracts.require_keys(row, fields, 'closed revision input group or pin')
            output.append({('app_artifact_id' if key == 'revision_artifact_id' else key):value for key,value in row.items()})
    return projected, projected_pins


def _signed_charge(groups):
    return sum(sum(len(body) for body in row['evidence_artifacts'].values())+
        sum(len(base._plain(row[key],8*1024**2)) for key in ('reviews','observed_artifact_sha256s','observed_pins')) for row in groups)


def _preflight_epoch(inputs, groups, pins, own_bounds):
    replay = inputs['adjudication_replay_inputs']
    if type(replay) is not dict or not application.REPLAY_REQUIRED <= set(replay) or set(replay)-application.REPLAY_REQUIRED-application.REPLAY_OPTIONAL:
        _fail('closed complete fixed upstream history replay inputs required')
    preparation = replay['preparation']
    contracts.require_keys(preparation, source.PREPARATION_KEYS, 'complete original preparation')
    if type(preparation['requests']) is not list or len(preparation['requests']) > own_bounds['max_groups']:
        _fail('complete bounded original epoch population required')
    source_bounds = source._limits(replay.get('source_review_limits'))
    response_bounds = responses._limits(replay.get('typed_response_limits'))
    adj_bounds = adjudication._limits(replay.get('limits'))
    responses._bindings(replay['response_bindings'], replay['expected_response_bindings_sha256'], preparation,
        replay['source_review_groups'], response_bounds, source_bounds, verify_hashes=False)
    adjudication._original_budget(replay['source_review_groups'],source_bounds)
    application._preflight(replay['adjudication_groups'], replay['expected_adjudication_group_pins'], preparation, adj_bounds, application=False)
    application._preflight(groups,pins,preparation,own_bounds,application=True)
    return sum(_signed_charge(values) for values in (replay['source_review_groups'],replay['adjudication_groups'],groups))


def _step_pin(step):
    replay = step['adjudication_replay_inputs']
    return {'epoch_id':step['epoch_id'], 'descriptor_sha256':_digest(step['descriptor']),
        'adjudication_manifest_sha256':step['expected_adjudication_manifest_sha256'],
        'registry_sha256':step['expected_revision_registry_sha256'], 'policy_sha256':step['expected_revision_policy_sha256'],
        'group_pins_sha256':_digest(step['expected_revision_group_pins']), 'evaluation_time_utc':replay['at_time_utc']}


def _preflight_all(genesis_report, genesis_inputs, steps, pins, bounds):
    if type(genesis_inputs) is not dict or not GENESIS_REQUIRED <= set(genesis_inputs) or set(genesis_inputs)-GENESIS_REQUIRED-{'limits'}:
        _fail('closed complete genesis replay inputs required')
    if type(steps) is not list or len(steps)+1 > bounds['max_epochs'] or type(pins) is not list or len(pins) != len(steps):
        _fail('complete bounded topological revision population and pins required')
    detached, size = _clone({'genesis_report':genesis_report,'genesis_inputs':genesis_inputs,'steps':steps,'pins':pins},bounds)
    genesis_report,genesis_inputs,steps,pins = (detached[key] for key in ('genesis_report','genesis_inputs','steps','pins'))
    total = _preflight_epoch(genesis_inputs,genesis_inputs['application_groups'],genesis_inputs['expected_application_group_pins'],
        application._limits(genesis_inputs.get('limits')))
    projected = []
    population = len(genesis_inputs['adjudication_replay_inputs']['preparation']['requests'])
    for step,pin in zip(steps,pins,strict=True):
        if type(step) is not dict or not STEP_REQUIRED <= set(step) or set(step)-STEP_REQUIRED-{'limits'}:
            _fail('closed complete revision epoch replay inputs required')
        contracts.require_keys(pin, STEP_PIN_FIELDS, 'independent complete revision epoch pins')
        groups,group_pins = _project(step['revision_groups'],step['expected_revision_group_pins'])
        total += _preflight_epoch(step,groups,group_pins,application._limits(step.get('limits')))
        population += len(step['adjudication_replay_inputs']['preparation']['requests'])
        projected.append((groups,group_pins))
        if total > bounds['max_all_signed_evidence_bytes']:
            _fail('whole-history mixed signed evidence exceeds bound before hashing')
    if total > bounds['max_all_signed_evidence_bytes'] or population > bounds['max_total_groups']:
        _fail('complete all-epoch signed budget or group population exceeds bound before hashing')
    for step,pin in zip(steps,pins,strict=True):
        if _step_pin(step) != pin:
            _fail('independent complete revision epoch pins differ')
    return genesis_report,genesis_inputs,steps,pins,projected,{**size,'all_epoch_signed_mixed_bytes':total,'total_groups':population}


def _epoch_metadata(genesis_inputs, steps, genesis_id, current_id, current_time):
    """Reject known name, scope, clock and population errors before replay."""
    from . import legal_graph_review as auth
    descriptor = application._descriptor(genesis_inputs['descriptor'])
    preparation_sha = genesis_inputs['adjudication_replay_inputs']['expected_preparation_manifest_sha256']
    contracts.require_sha256(preparation_sha,'fixed complete history preparation SHA256')
    ids = {genesis_id}
    evaluations = {genesis_id:auth._time(genesis_inputs['adjudication_replay_inputs']['at_time_utc'])}
    for step in steps:
        epoch_id = step['epoch_id']
        auth._id(epoch_id,'explicit revision epoch ID')
        if epoch_id in ids:
            _fail('duplicate history epoch aliases rejected before replay')
        ids.add(epoch_id)
        value = step['descriptor']
        contracts.require_keys(value,application.DESCRIPTOR_FIELDS,'fixed revision descriptor grammar')
        previous = _reference(value['previous_snapshot_manifest_ref'],'explicit predecessor manifest reference')
        if (value['snapshot_id'] != descriptor['snapshot_id'] or value['use_scope'] != application.USE_SCOPE
                or type(value['generation']) is not int or not 2 <= value['generation'] <= len(steps)+1
                or (previous['schema'] == application.MANIFEST_SCHEMA and value['generation'] != 2)):
            _fail('fixed snapshot/use scope and bounded revision generation required before replay')
        replay = step['adjudication_replay_inputs']
        if replay['expected_preparation_manifest_sha256'] != preparation_sha:
            _fail('source preparation migration rejected before historical replay')
        evaluations[epoch_id] = auth._time(replay['at_time_utc'])
    if current_id not in ids or evaluations[current_id] != current_time or any(value > current_time for value in evaluations.values()):
        _fail('all historical/current epoch selections must have compatible explicit times before replay')
    if current_id == genesis_id and steps:
        _fail('genesis cannot be selected as a leaf of a supplied revision history')


def _original_actors(inputs_list):
    principals,dids,public = set(),set(),set()
    from . import legal_graph_review as auth
    for inputs in inputs_list:
        replay = inputs['adjudication_replay_inputs']
        registry = application._trust(replay['source_registry'],replay['expected_registry_sha256'])
        policy = application._trust(replay['source_policy'],replay['expected_policy_sha256'])
        auth._trust(registry,policy,replay['expected_registry_sha256'],replay['expected_policy_sha256'],action=source.ACTION,audience=source.AUDIENCE)
        keys = registry['keys']
        known = {row['key_id']:row['public_key_hex'] for row in keys}
        for group in replay['source_review_groups']:
            for claim in group['reviews']:
                if type(claim) is not dict:
                    _fail('complete original reviewer claims required')
                for field,target in (('principal_id',principals),('signer_did',dids)):
                    value = claim.get(field)
                    if type(value) is not str:
                        _fail('original reviewer declared identity required')
                    target.add(value)
                key = claim.get('key_id')
                if type(key) is not str:
                    _fail('complete original reviewer key identity required')
                if key in known:
                    public.add(known[key])
    return principals,dids,public


def _revision_content(group, request, subject, upstream, parent_group, parent, descriptor, epoch_id, replay, root_sha, bounds):
    identity = group['app_artifact_id']
    if identity is None:
        return None,[]
    try:
        raw = group['evidence_artifacts'][identity]
        record = contracts.validate_record(base._load(raw,bounds['max_declaration_bytes']), schema=DECLARATION_SCHEMA,fields=DECLARATION_FIELDS)
        expected = record_source_revision_declaration(request,subject,upstream,parent_group,parent,descriptor,
            epoch_id=epoch_id, expected_request_sha256=_digest(request), expected_subject_sha256=_digest(subject),
            expected_adjudication_group_sha256=_digest(upstream), expected_previous_snapshot_group_sha256=_digest(parent_group),
            expected_previous_snapshot_manifest_sha256=_digest(parent), expected_preparation_manifest_sha256=replay['expected_preparation_manifest_sha256'],
            expected_typed_response_manifest_sha256=replay['expected_typed_response_manifest_sha256'],expected_adjudication_manifest_sha256=root_sha,
            declared_at_utc=record['declared_at_utc'], rationale=record['rationale'], evidence_refs=record['evidence_refs'],limits=bounds)
        if canonical_dag_json_bytes(record) != canonical_dag_json_bytes(expected):
            _fail('revision exact epoch/predecessor/current selection population differs')
        variants = {row['record_cid']:row for row in replay['typed_response_report']['answer_variants']}
        common = {'artifact_id':identity,'sha256':_sha(raw)}
        obligations = []
        for slot,ref in zip(request['context_slot_ids'],record['selected_answer_variant_refs'],strict=True):
            variant = variants[ref['record_cid']]
            if _ref(variant) != ref or variant['slot_id'] != slot or variant['request_cid'] != request['record_cid']:
                _fail('revision exact current typed variant differs')
            disposition = responses.DISPOSITIONS[variant['answer']['disposition']]
            if disposition == 'open':
                _fail('unresolved answer cannot activate a candidate revision')
            obligations.append({'slot_id':slot,'disposition':disposition,'evidence_refs':[common]})
        for ref in record['evidence_refs']:
            body = group['evidence_artifacts'].get(ref['artifact_id'])
            if ref['artifact_id'] == identity or body is None or _sha(body) != ref['sha256']:
                _fail('revision evidence missing changed or self-referential')
        for claim in group['reviews']:
            closure = claim['context_closure']
            if closure['obligations'] != obligations or closure['unresolved'] or closure['status'] != 'declared_complete':
                _fail('revision requires exact complete nine-slot signed activation')
        return record,[]
    except (ValueError,TypeError,KeyError,IndexError,RecursionError) as error:
        return None,[str(error)[:512] or 'invalid_revision_content']


def _pages(entries, bounds, schema, fields):
    pages,refs,pending,start = [],[],[],0
    def seal(items):
        return _seal(schema,page_ordinal=len(pages),first_group_ordinal=start,entries=items)
    def finish():
        if len(pages) >= bounds['max_pages']:
            _fail('complete source history page population exceeds bound')
        page = seal(pending)
        contracts.validate_record(page,schema=schema,fields=fields)
        base._plain(page,bounds['max_page_bytes'])
        pages.append(page)
        refs.append({**_ref(page),'page_ordinal':len(pages)-1,'first_group_ordinal':start,'entry_count':len(pending)})
    size,retained = len(canonical_dag_json_bytes(seal([]))),0
    for entry in entries:
        added = len(canonical_dag_json_bytes(entry))
        if pending and (len(pending) >= bounds['max_groups_per_page'] or size+retained+added+len(pending)+32 > bounds['max_page_bytes']):
            finish()
            start,pending,retained = entry['ordinal'],[],0
            size = len(canonical_dag_json_bytes(seal([])))
        pending.append(entry)
        retained += added
    if pending:
        finish()
    return pages,refs


def _assess_revision(step, parent_report, projected, original_actors):
    bounds = application._limits(step.get('limits'))
    parent = parent_report['manifest']
    descriptor = _descriptor(step['descriptor'],parent)
    from . import legal_graph_review as auth
    auth._id(step['epoch_id'],'revision epoch ID')
    evaluation_time = step['adjudication_replay_inputs']['at_time_utc']
    evaluation = auth._time(evaluation_time)
    parent_time = auth._time(parent['evaluation_time_utc'])
    if evaluation < parent_time:
        _fail('revision selected evaluation cannot precede predecessor evaluation')
    registry = application._trust(step['revision_registry'],step['expected_revision_registry_sha256'])
    policy = application._trust(step['revision_policy'],step['expected_revision_policy_sha256'])
    auth._trust(registry,policy,step['expected_revision_registry_sha256'],step['expected_revision_policy_sha256'],action=ACTION,audience=AUDIENCE)
    offered = adjudication._detach(step['adjudication_report'],adjudication._limits(step['adjudication_replay_inputs'].get('limits')))
    if _digest(offered['manifest']) != step['expected_adjudication_manifest_sha256']:
        _fail('independent current revision adjudication root differs')
    replay,groups = application._replay_inputs(step['adjudication_replay_inputs'],offered,*projected,bounds)
    preparation = replay['preparation']
    if (replay['expected_preparation_manifest_sha256'] != parent['preparation_manifest_sha256']
            or [row['request_cid'] for row in parent_report['records']] != [row['record_cid'] for row in preparation['requests']]):
        _fail('source preparation/request population migration is unsupported')
    checked = adjudication.validate_source_adjudications(offered,**replay)
    producer_pins = _pins()
    principals,dids,public = original_actors
    keys = {row['key_id']:row for row in registry['keys']}
    domain = auth._ReviewDomain(source.SUBJECT_SCHEMA,CLAIM_SCHEMA,ACTION,AUDIENCE,ASSESSMENT_SCHEMA,source._subject,source.ACTIVE_SLOT_COUNT)
    records,entries,retained,active,bodies,authenticated = [],[],0,0,0,0
    for ordinal,(request,subject,dependency,upstream,adjudication_group,prior_group,group,pin) in enumerate(zip(
            preparation['requests'],preparation['subjects'],preparation['dependency_manifests'],checked['records'],
            replay['adjudication_groups'],parent_report['records'],groups,projected[1],strict=True)):
        record,content_blockers = _revision_content(group,request,subject,upstream,prior_group,parent,descriptor,step['epoch_id'],replay,
            step['expected_adjudication_manifest_sha256'],bounds)
        assessment = auth._assess_reviews(subject,registry,policy,group['reviews'],dependency,domain=domain,
            expected_subject_sha256=_digest(subject),expected_registry_sha256=step['expected_revision_registry_sha256'],
            expected_policy_sha256=step['expected_revision_policy_sha256'],expected_reviews_sha256=pin['reviews_sha256'],
            expected_manifest_sha256=dependency['manifest_sha256'],at_time_utc=evaluation_time,
            observed_artifact_sha256s=group['observed_artifact_sha256s'],observed_pins=group['observed_pins'],evidence_artifacts=group['evidence_artifacts'])
        blockers = []
        if not upstream['authority_prerequisites_satisfied_under_selected_trust']:
            blockers.append('current_original_and_adjudication_authority_prerequisites_unavailable')
        if any(claim['principal_id'] in principals for claim in group['reviews']):
            blockers.append('revision_actor_is_a_supplied_historical_original_reviewer')
        if any(claim['signer_did'] in dids for claim in group['reviews']):
            blockers.append('revision_actor_reuses_a_historical_original_reviewer_did')
        if any(keys.get(claim['key_id'],{}).get('public_key_hex') in public for claim in group['reviews']):
            blockers.append('revision_actor_reuses_a_historical_original_reviewer_public_key')
        if record is not None:
            declared = auth._time(record['declared_at_utc'])
            if declared > evaluation:
                blockers.append('revision_declared_after_evaluation')
            if declared < parent_time:
                blockers.append('revision_predates_predecessor_selected_evaluation')
            if declared < auth._time(upstream['declaration_record']['declared_at_utc']) or any(declared < auth._time(claim['issued_at_utc']) for claim in adjudication_group['reviews']):
                blockers.append('revision_predates_current_adjudication')
            if any(auth._time(claim['issued_at_utc']) < declared for claim in group['reviews']):
                blockers.append('revision_claim_predates_common_declaration')
        eligible = record is not None and not content_blockers and not blockers and assessment['review_prerequisites_satisfied_under_selected_trust']
        identity = group['app_artifact_id']
        raw_ref = None if identity is None else {'artifact_id':identity,'sha256':_sha(group['evidence_artifacts'][identity])}
        result = _seal(REVISION_GROUP_SCHEMA,queue_ordinal=ordinal,request_cid=request['record_cid'],
            original_adjudication_group_record=upstream,previous_snapshot_group_ref=_ref(prior_group),
            application_declaration_artifact_ref=raw_ref,application_declaration_record=record,
            application_content_status='absent' if identity is None else 'valid_declared_content' if record is not None else 'rejected',
            content_blockers=content_blockers,authority_assessment=assessment,application_blockers=blockers,
            source_answer_snapshot_activated_under_selected_profile=eligible,
            activated_answer_variant_refs=record['selected_answer_variant_refs'] if eligible else [],
            deferred_review_slot_ids=request['deferred_review_slot_ids'],original_contexts_remain_required_unavailable=True)
        retained += len(base._plain(result,min(contracts.MAX_RECORD_BYTES,bounds['max_collection_bytes']-retained)))+1
        records.append(result)
        entries.append({'ordinal':ordinal,'request_cid':request['record_cid'],'group_record_ref':_ref(result)})
        active += int(eligible)
        bodies += int(identity is not None)
        authenticated += assessment['authenticated_evidence_count']
    pages,page_refs = _pages(entries,bounds,REVISION_PAGE_SCHEMA,REVISION_PAGE_FIELDS)
    manifest = _seal(REVISION_MANIFEST_SCHEMA,profile=REVISION_PROFILE,activation_effect=application.EFFECT,epoch_id=step['epoch_id'],
        snapshot_descriptor=descriptor,limits=bounds,adjudication_manifest_ref=_ref(checked['manifest']),
        preparation_manifest_sha256=replay['expected_preparation_manifest_sha256'],typed_response_manifest_sha256=replay['expected_typed_response_manifest_sha256'],
        application_registry_sha256=step['expected_revision_registry_sha256'],application_policy_sha256=step['expected_revision_policy_sha256'],
        application_group_pins=step['expected_revision_group_pins'],evaluation_time_utc=evaluation_time,producer_pins=producer_pins,page_refs=page_refs,
        counts={'groups':len(records),'pages':len(pages),'application_bodies':bodies,'authenticated_application_claims':authenticated,
            'activated_candidate_answer_snapshots':active,'activated_answer_slots':active*9,'blocked_groups':len(records)-active,
            'blocked_active_slots':(len(records)-active)*9,'deferred_questions':len(records)*7,'source_decisions_applied':0,'physical_governing_bindings_applied':0},population_complete=True)
    report = {'manifest':manifest,'pages':pages,'records':records}
    if source._aggregate_size(report) > bounds['max_collection_bytes'] or _pins() != producer_pins:
        _fail('complete revision output bound exceeded or producer pins changed')
    return report


def assess_source_history(genesis_report, genesis_inputs, revision_steps, *, genesis_epoch_id, current_epoch_id,
        at_time_utc, expected_genesis_manifest_sha256, expected_revision_step_pins, limits=None):
    """Regenerate each supplied epoch once; qualify current use separately."""
    bounds = _limits(limits)
    from . import legal_graph_review as auth
    auth._id(genesis_epoch_id,'explicit genesis epoch ID')
    auth._id(current_epoch_id,'explicit selected current epoch ID')
    current_time = auth._time(at_time_utc)
    contracts.require_sha256(expected_genesis_manifest_sha256,'independent genesis snapshot FULL SHA256')
    genesis_report,genesis_inputs,steps,pins,projected,_ = _preflight_all(genesis_report,genesis_inputs,revision_steps,expected_revision_step_pins,bounds)
    _epoch_metadata(genesis_inputs,steps,genesis_epoch_id,current_epoch_id,current_time)
    offered = application._detach(genesis_report,application._limits(genesis_inputs.get('limits')))
    if _digest(offered['manifest']) != expected_genesis_manifest_sha256:
        _fail('independent complete genesis snapshot root differs')
    all_actors = _original_actors([genesis_inputs,*steps])
    producer_pins = _pins()
    checked_genesis = application.validate_source_applications(offered,**genesis_inputs)
    epochs = [(genesis_epoch_id,'genesis',None,checked_genesis)]
    by_id = {genesis_epoch_id:checked_genesis}
    by_ref = {_digest(checked_genesis['manifest']):genesis_epoch_id}
    children = {genesis_epoch_id:[]}
    lineage_inputs = {genesis_epoch_id:[genesis_inputs]}
    step_by_id = {}
    for step,projection in zip(steps,projected,strict=True):
        epoch_id = step['epoch_id']
        auth._id(epoch_id,'revision epoch ID')
        if epoch_id in by_id:
            _fail('duplicate epoch aliases cannot replace a supplied node')
        descriptor = step['descriptor']
        contracts.require_keys(descriptor,application.DESCRIPTOR_FIELDS,'closed complete history revision descriptor')
        previous = _reference(descriptor['previous_snapshot_manifest_ref'],'topological predecessor reference')
        parent_id = by_ref.get(previous['sha256'])
        if parent_id is None or _ref(by_id[parent_id]['manifest']) != previous:
            _fail('exact predecessor must be an earlier supplied regenerated epoch')
        lineage = [*lineage_inputs[parent_id],step]
        report = _assess_revision(step,by_id[parent_id],projection,_original_actors(lineage))
        digest = _digest(report['manifest'])
        if digest in by_ref:
            _fail('duplicate snapshot roots cannot replace history nodes')
        epochs.append((epoch_id,'revision',parent_id,report))
        by_id[epoch_id] = report
        by_ref[digest] = epoch_id
        children.setdefault(parent_id,[]).append(epoch_id)
        children[epoch_id] = []
        lineage_inputs[epoch_id] = lineage
        step_by_id[epoch_id] = step
    if current_epoch_id not in by_id or children[current_epoch_id]:
        _fail('selected current epoch must be an explicitly supplied leaf')
    if auth._time(by_id[current_epoch_id]['manifest']['evaluation_time_utc']) != current_time:
        _fail('current snapshot must be regenerated at the explicit current evaluation')
    if any(auth._time(report['manifest']['evaluation_time_utc']) > current_time for _,_,_,report in epochs):
        _fail('historical selected epoch cannot postdate current evaluation')
    fork_ids = [epoch_id for epoch_id,_,_,_ in epochs if len(children[epoch_id]) > 1]
    fork_refs = [_ref(by_id[epoch_id]['manifest']) for epoch_id in fork_ids]
    leaves = [epoch_id for epoch_id,_,_,_ in epochs if not children[epoch_id]]
    current_step = step_by_id.get(current_epoch_id)
    current_keys = {} if current_step is None else {
        row['key_id']:row for row in current_step['revision_registry']['keys']}
    all_principals,all_dids,all_public = all_actors
    records,entries,epoch_records,epoch_pages,epoch_refs,retained,current_active,historical_active = [],[],[],[],[],0,0,0
    def charge(record):
        nonlocal retained
        retained += len(base._plain(record,min(contracts.MAX_RECORD_BYTES,bounds['max_collection_bytes']-retained)))+1
        return record
    for epoch_id,kind,parent_id,report in epochs:
        manifest = report['manifest']
        parent_ref = None if parent_id is None else _ref(by_id[parent_id]['manifest'])
        generation = manifest['snapshot_descriptor']['generation']
        epoch_record = charge(_seal(EPOCH_SCHEMA,epoch_id=epoch_id,kind=kind,generation=generation,previous_epoch_id=parent_id,snapshot_manifest_record=manifest))
        epoch_records.append(epoch_record)
        page_refs = []
        for page in report['pages']:
            wrapper = charge(_seal(EPOCH_PAGE_SCHEMA,epoch_id=epoch_id,page_ordinal=page['page_ordinal'],snapshot_page_record=page))
            epoch_pages.append(wrapper)
            page_refs.append(_ref(wrapper))
        epoch_refs.append({'epoch_id':epoch_id,'kind':kind,'generation':generation,'previous_epoch_id':parent_id,
            'manifest_ref':_ref(manifest),'epoch_record_ref':_ref(epoch_record),'epoch_page_refs':page_refs})
        for group in report['records']:
            blockers = []
            if epoch_id != current_epoch_id:
                blockers.append('historical_activation_cannot_supply_selected_current_eligibility')
            if kind == 'genesis':
                blockers.append('fresh_revision_authorization_required_for_current_history_use')
            if fork_ids:
                blockers.append('visible_forks_require_separate_resolution_profile')
            if not group['source_answer_snapshot_activated_under_selected_profile']:
                blockers.append('fresh_selected_epoch_authority_or_evidence_prerequisites_unavailable')
            if epoch_id == current_epoch_id and current_step is not None:
                claims = current_step['revision_groups'][group['queue_ordinal']]['reviews']
                if any(claim['principal_id'] in all_principals for claim in claims):
                    blockers.append('current_revision_actor_is_a_supplied_history_original_reviewer')
                if any(claim['signer_did'] in all_dids for claim in claims):
                    blockers.append('current_revision_actor_reuses_a_supplied_history_original_reviewer_did')
                if any(current_keys.get(claim['key_id'],{}).get('public_key_hex') in all_public for claim in claims):
                    blockers.append('current_revision_actor_reuses_a_supplied_history_original_reviewer_public_key')
            eligible = not blockers
            result = charge(_seal(GROUP_SCHEMA,epoch_id=epoch_id,generation=generation,queue_ordinal=group['queue_ordinal'],
                request_cid=group['request_cid'],snapshot_manifest_ref=_ref(manifest),previous_snapshot_manifest_ref=parent_ref,
                snapshot_group_record=group,regenerated_at_explicit_epoch_trust_and_time=True,
                current_candidate_refs_eligible_under_selected_history_profile=eligible,current_eligibility_blockers=blockers,
                current_active_answer_variant_refs=group['activated_answer_variant_refs'] if eligible else []))
            records.append(result)
            entries.append({'ordinal':len(records)-1,'epoch_id':epoch_id,'request_cid':group['request_cid'],'group_record_ref':_ref(result)})
            current_active += int(eligible)
            historical_active += int(group['source_answer_snapshot_activated_under_selected_profile'])
    pages,page_refs = _pages(entries,bounds,PAGE_SCHEMA,PAGE_FIELDS)
    manifest = _seal(MANIFEST_SCHEMA,profile=PROFILE,limits=bounds,genesis_epoch_id=genesis_epoch_id,
        snapshot_id=checked_genesis['manifest']['snapshot_descriptor']['snapshot_id'],use_scope=application.USE_SCOPE,
        preparation_manifest_sha256=checked_genesis['manifest']['preparation_manifest_sha256'],current_epoch_id=current_epoch_id,
        evaluation_time_utc=at_time_utc,epoch_refs=epoch_refs,leaf_epoch_ids=leaves,fork_parent_manifest_refs=fork_refs,
        revision_step_pins=pins,producer_pins=producer_pins,page_refs=page_refs,
        counts={'epochs':len(epochs),'revision_epochs':len(steps),'groups_per_epoch':len(checked_genesis['records']),
            'total_groups':len(records),'pages':len(pages),'epoch_pages':len(epoch_pages),'visible_fork_parents':len(fork_ids),
            'historical_activated_groups_at_selected_epoch_times':historical_active,'current_eligible_groups':current_active,
            'current_eligible_answer_slots':current_active*9,'current_blocked_groups':len(by_id[current_epoch_id]['records'])-current_active,
            'current_blocked_active_slots':(len(by_id[current_epoch_id]['records'])-current_active)*9,
            'deferred_questions_per_epoch':len(checked_genesis['records'])*7,'source_decisions_applied':0,'physical_governing_bindings_applied':0},
        population_complete_for_supplied_history=True)
    result = {'manifest':manifest,'pages':pages,'records':records,'epoch_manifests':epoch_records,'epoch_pages':epoch_pages}
    if source._aggregate_size(result) > bounds['max_collection_bytes'] or _pins() != producer_pins:
        _fail('complete history output bound exceeded or producers changed')
    return result


def _detach(report, bounds):
    contracts.require_keys(report,COMPONENTS,'complete supplied history report')
    result,retained = {},0
    for key,schema,fields,cap in (('manifest',MANIFEST_SCHEMA,MANIFEST_FIELDS,1),('pages',PAGE_SCHEMA,PAGE_FIELDS,bounds['max_pages']),
            ('records',GROUP_SCHEMA,GROUP_FIELDS,bounds['max_total_groups']),('epoch_manifests',EPOCH_SCHEMA,EPOCH_FIELDS,bounds['max_epochs']),
            ('epoch_pages',EPOCH_PAGE_SCHEMA,EPOCH_PAGE_FIELDS,bounds['max_epochs']*adjudication.DEFAULT_LIMITS['max_pages'])):
        values = [report[key]] if key == 'manifest' else report[key]
        if type(values) is not list or len(values) > cap:
            _fail('complete bounded source history component required')
        rows = []
        for value in values:
            maximum = bounds['max_page_bytes'] if key == 'pages' else contracts.MAX_RECORD_BYTES
            raw = base._plain(value,min(maximum,bounds['max_collection_bytes']-retained))
            retained += len(raw)+1
            rows.append(contracts.validate_record(base._load(raw,maximum),schema=schema,fields=fields))
        result[key] = rows[0] if key == 'manifest' else rows
    if source._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail('complete offered source history collection exceeds bound')
    return result


def validate_source_history(report, *args, **kwargs):
    checked = _detach(report,_limits(kwargs.get('limits')))
    expected = assess_source_history(*args,**kwargs)
    source._equal_components(checked,expected)
    if _pins() != expected['manifest']['producer_pins']:
        _fail('history producers changed during final comparison')
    return checked


__all__ = ['record_source_revision_declaration','validate_source_revision_declaration',
    'assess_source_history','validate_source_history']
