"""Shared typed responses preserve exact legacy reports and fresh trust checks.

All signed cases are fictional. The retained13sources/16physicalrows/150candidates
supply no actual credentials or typed bodies: all32planned slots remain missing.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import stat
import pytest
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review as legacy_review
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_responses as legacy_responses
from ipfs_datasets_py.logic.autoformal import legal_graph_review as trust_owner
from ipfs_datasets_py.logic.autoformal import legal_source_correspondence_requests_v1 as correspondence
from ipfs_datasets_py.logic.autoformal import legal_shared_source_replay_v1 as shared_owner
from ipfs_datasets_py.logic.autoformal import legal_shared_bank_source_responses_v1 as owner
ROOT=Path('/home/barberb/lift_coding')
REAL_INPUTS=ROOT/'artifacts/legal-ir-shared-bank-responses-20261019-01/inputs.json'
REAL_INPUTS_BYTES=12696
REAL_INPUTS_SHA256='7be86b69277ef0d4b060b6ead8508a12834607887e39bea910381210f4d966d9'
EVIDENCE_NAME='shared-bank-responses-engineering-evidence.json'
PROFILE='shared-original-catalog-planned-replay/v1'
ORDINALS=[2720,2721,2722,2724,2726,2727,3345,3352,3353,3354,3355,3357,3358]
EPOCHS=[{'epoch_id':'plan:root','parent_epoch_id':None},
        {'epoch_id':'plan:second','parent_epoch_id':'plan:root'}]
PARSER_PROFILES={'join':'legacy-source-join-canonical-record/v1',
 'paired':'paired-span-census-record/v1','receipt':'legacy-producer-receipt-json/v1'}
SOURCE_PREIMAGE={'path':str(ROOT/'artifacts/legal-ir-shared-bank-responses-20261019-01/source-preimages/corpus_legacy_source_review.py'),
 'bytes':22233,'sha256':'29d5fd7c03b7ef150a4429cb3ca0e86f830a160b20860424b6a7354b778545d0'}
RESPONSE_PREIMAGE={'path':str(ROOT/'artifacts/legal-ir-shared-bank-responses-20261019-01/source-preimages/corpus_legacy_source_responses.py'),
 'bytes':22314,'sha256':'64963cff721c358eca48682be95c574a23f854a4e22350661be261a5c4e6b858'}

def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_ref(raw):
    return {'bytes': len(raw), 'sha256': sha(raw)}


def fixture_helper():
    path = Path(__file__).with_name('test_legal_source_correspondence_requests_v1.py')
    spec = importlib.util.spec_from_file_location('fictional_correspondence_for_shared_replay', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def independently_catalog(banks):
    """Published descriptor/origin recipes, independently authored from raw bytes."""
    records, origins, bank_rows, bodies = {}, [], [], {}
    for bank in banks:
        bank_id = bank['bank_id']
        root = {'bank_id': bank_id, 'join_origin_id': None, 'paired_origin_ids': [], 'producer_receipt_origin_id': None}
        items = [('join', None, bank['join_bytes'])]
        items += [('paired', index, raw) for index, raw in enumerate(bank['paired_row_bytes'])]
        if bank['join_inputs']['producer_receipt_bytes'] is not None:
            items.append(('receipt', None, bank['join_inputs']['producer_receipt_bytes']))
        for kind, ordinal, raw in items:
            key = {**raw_ref(raw), 'media_type': 'application/json', 'parser_profile': PARSER_PROFILES[kind]}
            content_id = 'sha256:' + sha(wire(key))
            if content_id in bodies: assert bodies[content_id] == raw
            bodies[content_id] = raw
            records[content_id] = {'content_id': content_id, **key}
            origin_key = {'bank_id': bank_id, 'kind': kind, 'logical_row_ordinal': ordinal}
            origin_id = 'sha256:' + sha(wire(origin_key))
            origins.append({'origin_id': origin_id, **origin_key, 'content_id': content_id,
                            'raw_sha256': key['sha256'], 'raw_bytes': key['bytes']})
            if kind == 'join': root['join_origin_id'] = origin_id
            elif kind == 'paired': root['paired_origin_ids'].append(origin_id)
            else: root['producer_receipt_origin_id'] = origin_id
        bank_rows.append(root)
    ordered = [records[key] for key in sorted(records)]
    receipts = [row for row in ordered if row['parser_profile'] == PARSER_PROFILES['receipt']]
    return {'schema': 'legal-shared-source-original-catalog/v1', 'profile': PROFILE,
        'records': ordered, 'origins': origins, 'banks': bank_rows,
        'coverage': {'content_records': len(ordered), 'origin_references': len(origins),
            'unique_content_bytes': sum(row['bytes'] for row in ordered),
            'origin_reference_bytes': sum(row['raw_bytes'] for row in origins),
            'unique_receipt_bytes': sum(row['bytes'] for row in receipts),
            'receipt_origin_bytes': sum(row['raw_bytes'] for row in origins if row['kind'] == 'receipt')}}


def independently_schedule(banks, epochs, catalog):
    requests = []; expanded = receipt_bytes = physical = 0
    by_bank = {row['bank_id']: row for row in catalog['banks']}
    children = {row['epoch_id']: [] for row in epochs}
    for epoch in epochs:
        if epoch['parent_epoch_id'] is not None:
            children[epoch['parent_epoch_id']].append(epoch['epoch_id'])
        for bank in banks:
            origins = by_bank[bank['bank_id']]
            receipt = bank['join_inputs']['producer_receipt_bytes']
            size = 0 if receipt is None else len(receipt)
            for ordinal, raw in enumerate(bank['paired_row_bytes']):
                locators = [row['physical_row_ordinal'] for row in bank['physical_rows'] if row['request_ordinal'] == ordinal]
                requests.append({'epoch_id': epoch['epoch_id'], 'bank_id': bank['bank_id'], 'request_ordinal': ordinal,
                    'join_origin_id': origins['join_origin_id'], 'paired_origin_id': origins['paired_origin_ids'][ordinal],
                    'producer_receipt_origin_id': origins['producer_receipt_origin_id'], 'physical_row_ordinals': locators})
                expanded += len(bank['join_bytes']) + len(raw) + size
                receipt_bytes += size; physical += len(locators)
    return {'schema': 'legal-shared-source-planned-schedule/v1', 'profile': PROFILE, 'epochs': deepcopy(epochs),
        'requests': requests, 'forks': [{'parent_epoch_id': row['epoch_id'], 'child_epoch_ids': children[row['epoch_id']]}
            for row in epochs if len(children[row['epoch_id']]) > 1],
        'coverage': {'epochs': len(epochs), 'scheduled_logical_requests': len(requests),
            'scheduled_physical_references': physical, 'expanded_reference_bytes': expanded,
            'expanded_receipt_reference_bytes': receipt_bytes, 'legacy_history_input_cap': 512 * 1024**2,
            'receipt_reference_lower_bound_exceeds_legacy_cap': receipt_bytes > 512 * 1024**2}}


def replay_request(banks, epochs):
    catalog = independently_catalog(banks)
    schedule = independently_schedule(banks, epochs, catalog)
    return {'schema': 'legal-shared-source-replay-request/v1', 'profile': PROFILE,
        'bank_commitments': [{'bank_id': bank['bank_id'], 'original_bank_sha256': fixture_helper().original_bank_sha256(bank)} for bank in banks],
        'catalog_sha256': sha(wire(catalog)), 'schedule_sha256': sha(wire(schedule)), 'epochs': deepcopy(epochs)}


def read_exact(reference):
    path = Path(reference['path'])
    assert path.is_absolute() and path.resolve(strict=True) == path
    assert all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == reference['bytes']
        assert 0 < before.st_size <= 32 * 1024**2
        raw = stream.read(reference['bytes'] + 1)
        after = os.fstat(stream.fileno())
    identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    assert identity(before) == identity(after) == identity(path.lstat())
    assert len(raw) == reference['bytes'] and sha(raw) == reference['sha256']
    return raw


def read_json(reference):
    raw = read_exact(reference)
    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite original')))


def physical_source_key(provenance):
    return {key: provenance[key] for key in ('repository_id', 'revision', 'path_in_repo',
            'artifact_sha256', 'artifact_bytes', 'parquet_row_index')}


def auth_helper():
    path = Path(__file__).with_name('test_corpus_legacy_source_review_auth.py')
    spec = importlib.util.spec_from_file_location('fictional_signed_source_review_leaf', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def source_arguments(data, *, limits=None):
    return {'expected_packet_sha256': sha(wire(data['packet'])),
        'expected_source_request_sha256': sha(data['source_request_raw']),
        'expected_replay_request_sha256': sha(wire(data['replay_request'])),
        'original_banks': data['banks'], 'limits': limits}


def assemble(banks, *, epochs=None):
    source_raw = wire(fixture_helper().request_for(banks))
    packet = correspondence.prepare_source_correspondence_requests_v1(source_raw,
        expected_request_sha256=sha(source_raw), original_banks=banks)
    data = {'banks': banks, 'packet': packet, 'source_request_raw': source_raw,
        'replay_request': replay_request(banks, EPOCHS if epochs is None else epochs)}
    data['shared_report'] = shared_owner.prepare_shared_source_replay_v1(packet,
        source_raw, wire(data['replay_request']), **source_arguments(data))
    return data


def calls_sha256(calls):
    declared=deepcopy(calls)
    for call in declared:
        inputs=call.get('response_inputs')
        if inputs is not None:
            inputs['evidence_artifacts']={key:raw_ref(raw) for key,raw in inputs['evidence_artifacts'].items()}
    return sha(wire(declared))


def arguments(data, *, limits=None):
    return {'expected_shared_report_sha256':sha(wire(data['shared_report'])),
        'expected_response_calls_sha256':calls_sha256(data['response_calls']),
        **source_arguments(data, limits=limits)}


def assess(data, *, limits=None):
    return owner.assess_shared_bank_source_responses_v1(data['shared_report'],data['packet'],
        data['source_request_raw'],wire(data['replay_request']),data['response_calls'],
        **arguments(data,limits=limits))


def validate(report,data,*,limits=None):
    return owner.validate_shared_bank_source_responses_v1(report,data['shared_report'],data['packet'],
        data['source_request_raw'],wire(data['replay_request']),data['response_calls'],
        expected_report_sha256=sha(wire(report)),**arguments(data,limits=limits))


def flags(report):
    assert report['authority'] and all(value is False for value in report['authority'].values())
    assert type(report['training_mask']) is type(report['evaluation_gold_mask']) is int
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert report['inference_view'] is None


def refresh_call(data, *, index=1, damage):
    signed={key:deepcopy(value) for key,value in data['signed'].items() if key!='signers'}
    # Private keys are immutable cryptographic handles; deep-copy the wire inputs only.
    signed['signers']=data['signed']['signers']
    key=signed['registry']['keys'][0]
    if damage=='signature': signed['reviews'][0]['interpretation']['rationale']+=' unsigned edit'
    elif damage=='role': key['roles']=['formal_review']
    elif damage=='scope': key['scope_ids']=['fixture:unrelated-scope']
    elif damage=='key_revoked': key['revoked_at_utc']=auth_helper().NOW
    elif damage=='principal_revoked': signed['registry']['revoked_principals']=[{'principal_id':key['principal_id'],'revoked_at_utc':auth_helper().NOW}]
    elif damage=='key_expired': key['valid_until_utc']=auth_helper().NOW
    elif damage=='review_expired': signed['reviews'][0]['expires_at_utc']=auth_helper().NOW
    elif damage=='future_review': signed['reviews'][0]['issued_at_utc']='2026-10-14T10:00:00Z'
    elif damage=='stale_review': signed['policy']['max_review_age_seconds']=10
    elif damage=='registry_expired': signed['registry']['valid_until_utc']=auth_helper().NOW
    elif damage=='policy_expired': signed['policy']['valid_until_utc']=auth_helper().NOW
    elif damage=='unknown_key': signed['reviews'][0]['key_id']='fixture:unknown-key'
    elif damage=='same_principal':
        signed['registry']['keys'][1]['principal_id']=key['principal_id'];signed['reviews'][1]['principal_id']=key['principal_id']
    elif damage=='wrong_subject': signed['reviews'][0]['subject']['scope_id']='fixture:other-source-request'
    elif damage=='artifact': signed['observed_artifact_sha256s'][signed['preparation']['subjects'][0]['graph_id']]='0'*64
    elif damage=='missing_artifact': signed['observed_artifact_sha256s'].pop(signed['preparation']['subjects'][0]['graph_id'])
    elif damage=='evidence': signed['evidence_artifacts']['fixture:legacy-source-declaration']+=b' changed'
    elif damage=='omit_slot': signed['reviews'][0]['context_closure']['obligations'].pop()
    elif damage=='open_slot': signed['reviews'][0]['context_closure']['obligations'][0]['disposition']='open'
    elif damage=='no_evidence': signed['reviews'][0]['context_closure']['obligations'][0]['evidence_refs']=[]
    elif damage=='unresolved': signed['reviews'][0]['context_closure']['unresolved']=['Unresolved fictional context']
    elif damage=='conflict': signed['reviews'][0]['interpretation']['decision']='reject'
    elif damage=='ambiguity': signed['reviews'][0]['interpretation']['ambiguity']=['Fictional ambiguity']
    elif damage=='old_policy_action': signed['policy']['action']='record_source_context_review_evidence/v1'
    elif damage=='old_claim_domain':
        signed['reviews'][0].update(schema=trust_owner.CLAIM_SCHEMA,action=trust_owner.ACTION,audience=trust_owner.AUDIENCE)
    elif damage=='deferred_slot':
        slot=deepcopy(signed['reviews'][0]['context_closure']['obligations'][0]);slot['slot_id']=signed['preparation']['subjects'][0]['deferred_review_slot_ids'][0]
        signed['reviews'][0]['context_closure']['obligations'].append(slot)
    else: raise AssertionError(damage)
    if damage!='signature': auth_helper().refresh_signatures(signed)
    data['response_calls'][index]['response_inputs']=assessment_inputs(signed)
    return signed


def response_helper():
    path=Path(__file__).with_name('test_corpus_legacy_source_responses.py')
    spec=importlib.util.spec_from_file_location('fictional_typed_source_response_fixture',path)
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def pinned_module(reference,name):
    path=Path(reference['path']);raw=path.read_bytes()
    assert raw_ref(raw)=={key:reference[key] for key in ('bytes','sha256')}
    spec=importlib.util.spec_from_file_location('ipfs_datasets_py.logic.autoformal.'+name,path)
    assert spec is not None and spec.loader is not None
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def frozen_old_source_owner():
    return pinned_module(SOURCE_PREIMAGE,'_frozen_source_review_for_typed_batch')


def frozen_old_response_owner():
    module=pinned_module(RESPONSE_PREIMAGE,'_frozen_source_responses_for_typed_batch')
    # Link only these genuine private oracle modules; canonical owners remain intact.
    module.source=frozen_old_source_owner()
    return module


def assessment_inputs(signed):
    return {name:deepcopy(signed[name]) for name in ('registry','policy','reviews',
        'observed_artifact_sha256s','observed_pins','evidence_artifacts','response_bindings')} | {
        'expected_preparation_manifest_sha256':sha(wire(signed['preparation']['manifest'])),
        'expected_registry_sha256':sha(wire(signed['registry'])),
        'expected_policy_sha256':sha(wire(signed['policy'])),
        'expected_reviews_sha256':sha(wire(signed['reviews'])),
        'expected_response_bindings_sha256':sha(wire(signed['response_bindings'])),
        'at_time_utc':auth_helper().NOW}


def material(*,disposition='evidence_declared',epochs=None,fanout=False):
    signed=response_helper().response_case(legacy_responses,disposition=disposition)
    args=signed['arguments']
    join_inputs={key:deepcopy(value) for key,value in args.items()
        if key not in {'join_bytes','paired_row_bytes','expected_join_sha256'}}
    physical=[{'physical_row_ordinal':index,'request_ordinal':index,
        'physical_identity':{'repository_id':'fixture:typed-cache','revision':'2'*40,
            'path_in_repo':'fictional/typed.parquet','artifact_sha256':sha(b'fictional typed cache'),
            'row_ordinal':index}} for index in range(len(args['paired_row_bytes']))]
    if fanout:
        physical.append({'physical_row_ordinal':len(physical),'request_ordinal':0,
            'physical_identity':{**physical[0]['physical_identity'],'row_ordinal':len(physical)}})
    data=assemble([{'bank_id':'fixture:typed-bank','join_bytes':args['join_bytes'],
        'paired_row_bytes':deepcopy(args['paired_row_bytes']),'join_inputs':join_inputs,
        'physical_rows':physical}],epochs=epochs)
    assert data['packet']['banks'][0]['preparation']==signed['preparation']
    data['signed']=signed
    data['response_calls']=[{'epoch_id':row['epoch_id'],'bank_id':row['bank_id'],
        'request_ordinal':row['request_ordinal'],'response_inputs':assessment_inputs(signed)}
        for row in data['shared_report']['schedule']['requests']]
    return data


def old_assess(data,call):
    bank=next(bank for bank in data['banks'] if bank['bank_id']==call['bank_id'])
    preparation=next(bank['preparation'] for bank in data['packet']['banks'] if bank['bank_id']==call['bank_id'])
    params=deepcopy(call['response_inputs'])
    registry,policy,reviews=(params.pop(key) for key in ('registry','policy','reviews'))
    static={'request_ordinal':call['request_ordinal'],'join_bytes':bank['join_bytes'],
        'paired_row_bytes':bank['paired_row_bytes'],'expected_join_sha256':sha(bank['join_bytes']),
        **deepcopy(bank['join_inputs'])}
    original=frozen_old_response_owner()
    result=original.assess_legacy_source_responses(preparation,registry,policy,reviews,**static,**params)
    raw_params={key:value for key,value in params.items()
        if key not in {'response_bindings','expected_response_bindings_sha256'}}
    assert result['raw_source_assessment']==original.source.assess_legacy_source_review(
        preparation,registry,policy,reviews,**static,**raw_params)
    return result


def changed_signed(data):
    return {key:deepcopy(value) for key,value in data['signed'].items() if key!='signers'} | {
        'signers':data['signed']['signers']}


def use_second_call(data,signed):
    data['response_calls'][1]['response_inputs']=assessment_inputs(signed)


def install_response(signed,index,response):
    body=response_helper().record(legacy_responses,signed,response)
    response_helper().install_record(signed,index,body)
    return body


def reseal_body(body):
    from ipfs_datasets_py.logic.autoformal import corpus_contracts
    return corpus_contracts.seal_record({key:deepcopy(value) for key,value in body.items()
        if key not in {'record_cid','cid_scope'}})


def typed_mutation(data,damage):
    signed=changed_signed(data);helper=response_helper()
    if damage in {'missing_binding','duplicate_binding','reordered_binding'}:
        if damage=='missing_binding':signed['response_bindings'].pop()
        elif damage=='duplicate_binding':signed['response_bindings'][1]=deepcopy(signed['response_bindings'][0])
        else:signed['response_bindings'].reverse()
    elif damage in {'missing_body','changed_body','missing_support','changed_support'}:
        key=signed['response_bindings'][0]['artifact_id'] if damage.endswith('body') else 'fixture:legacy-source-declaration'
        if damage.startswith('missing'):signed['evidence_artifacts'].pop(key)
        else:signed['evidence_artifacts'][key]+=b' changed'
    elif damage in {'closure_status','closure_unresolved','closure_disposition','closure_ref','closure_extra_ref'}:
        closure=signed['reviews'][0]['context_closure']
        if damage=='closure_status':closure['status']='open'
        elif damage=='closure_unresolved':closure['unresolved']=[closure['obligations'][0]['slot_id']]
        elif damage=='closure_disposition':closure['obligations'][0]['disposition']='not_applicable'
        else:
            ref={'artifact_id':'fixture:legacy-source-declaration','sha256':sha(signed['evidence_artifacts']['fixture:legacy-source-declaration'])}
            if damage=='closure_ref':closure['obligations'][0]['evidence_refs']=[ref]
            else:closure['obligations'][0]['evidence_refs'].append(ref)
        auth_helper().refresh_signatures(signed)
    elif damage in {'variant','ambiguous','exposure_unknown','exposure_different','proposals'}:
        indexes=range(2) if damage=='proposals' else [1]
        for index in indexes:
            response=deepcopy(signed['responses'][index])
            if damage=='variant':response['answers'][0]['finding']['statement']='A distinct fictional finding.'
            elif damage=='ambiguous':
                answer=response['answers'][0];answer['disposition']='unresolved';answer['finding']['status']='ambiguous';answer['evidence_refs']=[]
            elif damage=='exposure_unknown':response['exposure_declaration']['organizer_source_metadata_exposed']=None
            elif damage=='exposure_different':response['exposure_declaration']['candidate_interpretations_exposed']=True
            else:
                response['occurrence_proposal'].update(status='proposed_present_day',
                    candidate_occurrence_cid=signed['joined']['rows'][0]['candidates'][index]['source_occurrence']['record_cid'],
                    evidence_refs=deepcopy(response['answers'][0]['evidence_refs']))
            install_response(signed,index,response)
    elif damage=='noncanonical_body':
        binding=signed['response_bindings'][0];raw=json.dumps(signed['response_records'][0],ensure_ascii=False,indent=2).encode()
        signed['evidence_artifacts'][binding['artifact_id']]=raw;binding['raw_sha256']=sha(raw)
        for obligation in signed['reviews'][0]['context_closure']['obligations']:obligation['evidence_refs'][0]['sha256']=sha(raw)
        auth_helper().refresh_signatures(signed)
    elif damage=='empty_population':signed['reviews']=[];signed['response_bindings']=[]
    else:
        body=deepcopy(signed['response_records'][0]);answer=body['answers'][0]
        if damage=='unsupported_finding':answer['finding']['status']='proven'
        elif damage=='ambiguous_resolved':answer['finding']['status']='ambiguous'
        elif damage=='missing_answer':body['answers'].pop()
        elif damage=='reordered_answers':body['answers'][:2]=reversed(body['answers'][:2])
        elif damage=='deferred_answer':answer['slot_id']=signed['preparation']['subjects'][0]['deferred_review_slot_ids'][0]
        elif damage=='wrong_source_binding':body['source_binding_sha256']='0'*64
        elif damage=='wrong_subject':body['subject_ref']['sha256']='0'*64
        elif damage=='wrong_request':body['request_ordinal']=1
        elif damage=='reviewer_identity':body['principal_id']='fixture:other-person'
        elif damage=='boolean_alias':body['request_ordinal']=False
        elif damage=='numeric_authority_alias':body['admitted']=0
        else:raise AssertionError(damage)
        if damage not in {'boolean_alias','numeric_authority_alias'}:body=reseal_body(body)
        helper.install_record(signed,0,body)
    use_second_call(data,signed)
    return signed
@pytest.mark.parametrize('disposition',['evidence_declared','not_applicable','unresolved'])
def test_complete_typed_outputs_match_both_independent_old_owners(disposition,monkeypatch):
    data=material(disposition=disposition)
    expected=[old_assess(data,call) for call in data['response_calls']]
    assert response_helper().assess(legacy_responses,data['signed'])==expected[0]
    assert [response_helper().record(frozen_old_response_owner(),data['signed'],response)
        for response in data['signed']['responses']]==data['signed']['response_records']
    original=legacy_review.prepare_legacy_source_review_requests;bank_calls=[]
    def counted_bank(*args,**kwargs):
        result=original(*args,**kwargs);bank_calls.append(1);return result
    original_auth=trust_owner._assess_reviews;auth_calls=[]
    def counted_auth(*args,**kwargs):
        result=original_auth(*args,**kwargs);auth_calls.append(1);return result
    original_content=legacy_responses._content;content_calls=[]
    def counted_content(*args,**kwargs):
        result=original_content(*args,**kwargs);content_calls.append(1);return result
    monkeypatch.setattr(legacy_review,'prepare_legacy_source_review_requests',counted_bank)
    monkeypatch.setattr(trust_owner,'_assess_reviews',counted_auth)
    monkeypatch.setattr(legacy_responses,'_content',counted_content)
    report=assess(data)
    assert (len(bank_calls),len(auth_calls),len(content_calls))==(1,2,4)
    assert [row['assessment'] for row in report['rows']]==expected
    assert [row['assessment_sha256'] for row in report['rows']]==[sha(wire(item)) for item in expected]
    assert report['work']=={'bank_context_prepare_calls':1,'source_bank_preparations':1,
        'private_preparation_capability_mints':1,'fresh_typed_response_assessments':2,
        'fresh_source_assessments':2,'fresh_fixed_domain_verifier_calls':2,
        'typed_response_content_checks':4,'source_bank_reparses_during_assessment':0,
        'history_epoch_replays':0,'authority_cache_hits':0}
    assert validate(report,data)==report
    assert owner.shared_bank_source_responses_sha256(report)==sha(wire(report))
    for item in expected:response_helper().no_decision(item)
    flags(report)


@pytest.mark.parametrize('damage',['signature','role','scope','key_revoked','principal_revoked',
    'key_expired','review_expired','future_review','stale_review','registry_expired',
    'policy_expired','unknown_key','same_principal','wrong_subject','artifact','missing_artifact',
    'old_policy_action','old_claim_domain'])
def test_every_typed_call_rechecks_fresh_source_trust_without_using_prior_positive(damage):
    data=material();baseline=old_assess(data,data['response_calls'][0]);refresh_call(data,damage=damage)
    try:changed=old_assess(data,data['response_calls'][1])
    except ValueError:
        with pytest.raises(ValueError):assess(data)
    else:
        report=assess(data)
        assert report['rows'][0]['assessment']==baseline
        assert report['rows'][1]['assessment']==changed and changed!=baseline
        assert len(changed['response_results'])==len(data['response_calls'][1]['response_inputs']['reviews'])
        response_helper().no_decision(changed);flags(report)


@pytest.mark.parametrize('damage',['missing_binding','duplicate_binding','reordered_binding',
    'missing_body','changed_body','missing_support','changed_support',
    'closure_status','closure_unresolved','closure_disposition','closure_ref','closure_extra_ref',
    'variant','ambiguous','exposure_unknown','exposure_different','proposals','noncanonical_body','empty_population',
    'unsupported_finding','ambiguous_resolved','missing_answer','reordered_answers','deferred_answer',
    'wrong_source_binding','wrong_subject','wrong_request','reviewer_identity','boolean_alias','numeric_authority_alias'])
def test_full_typed_body_binding_content_variants_and_refusals_match_old_owners(damage):
    data=material();baseline=old_assess(data,data['response_calls'][0]);typed_mutation(data,damage)
    try:changed=old_assess(data,data['response_calls'][1])
    except ValueError:
        with pytest.raises(ValueError):assess(data)
    else:
        report=assess(data)
        assert report['rows'][0]['assessment']==baseline
        assert report['rows'][1]['assessment']==changed and changed!=baseline
        assert len(changed['response_results'])==len(data['response_calls'][1]['response_inputs']['reviews'])
        assert report['work']['typed_response_content_checks']==len(baseline['response_results'])+len(changed['response_results'])
        if damage=='variant':assert changed['counts']['different_answer_slots']==1
        if damage=='ambiguous':assert changed['counts']['unresolved_answer_slots']==1
        if damage=='proposals':assert changed['counts']['differing_occurrence_proposals']==1
        if damage=='changed_support':assert changed['counts']['rejected_content_responses']==2
        if damage=='empty_population':assert changed['counts']['missing_authenticated_answer_slots']==9
        response_helper().no_decision(changed);flags(report)


@pytest.mark.parametrize('when',['2026-10-14T07:00:00Z','2026-10-15T09:00:00Z'])
def test_typed_results_use_each_call_explicit_clock(when):
    data=material();data['response_calls'][1]['response_inputs']['at_time_utc']=when
    expected=[old_assess(data,call) for call in data['response_calls']]
    report=assess(data)
    assert [row['assessment'] for row in report['rows']]==expected
    assert expected[0]!=expected[1];flags(report)


def test_missing_typed_inputs_remain_unassessed_without_empty_registry_substitution():
    data=material();data['response_calls'][1]['response_inputs']=None
    report=assess(data)
    assert report['rows'][0]['assessment']==old_assess(data,data['response_calls'][0])
    assert report['rows'][1]['assessment'] is None
    assert report['rows'][1]['assessment_status']=='not_assessed_missing_inputs'
    assert report['work']['fresh_typed_response_assessments']==1
    assert report['work']['typed_response_content_checks']==2;flags(report)


def test_typed_forks_and_physical_fanout_preserve_full_separate_populations():
    epochs=[{'epoch_id':'plan:root','parent_epoch_id':None},
        {'epoch_id':'plan:left','parent_epoch_id':'plan:root'},
        {'epoch_id':'plan:right','parent_epoch_id':'plan:root'}]
    data=material(epochs=epochs,fanout=True);report=assess(data)
    assert [row['assessment'] for row in report['rows']]==[old_assess(data,call) for call in data['response_calls']]
    assert len(report['rows'])==3 and all(len(row['physical_references'])==2 for row in report['rows'])
    assert report['coverage']['physical_references']==6
    assert report['work']['fresh_typed_response_assessments']==3;flags(report)


@pytest.mark.parametrize('damage',['drop','duplicate','reverse','epoch','bank','ordinal_bool','ordinal_other','extra'])
def test_complete_ordered_response_call_roster_refuses_before_bank_replay(damage,monkeypatch):
    data=material();calls=data['response_calls']
    if damage=='drop':calls.pop()
    elif damage=='duplicate':calls[1]=deepcopy(calls[0])
    elif damage=='reverse':calls.reverse()
    elif damage=='epoch':calls[0]['epoch_id']='plan:unknown'
    elif damage=='bank':calls[0]['bank_id']='fixture:wrong-bank'
    elif damage=='ordinal_bool':calls[0]['request_ordinal']=False
    elif damage=='ordinal_other':calls[0]['request_ordinal']=1
    else:calls[0]['cached_typed_assessment']={'authenticated_typed_responses':2}
    def forbidden(*args,**kwargs):raise AssertionError('invalid typed roster must refuse before original replay')
    monkeypatch.setattr(legacy_review,'prepare_legacy_source_review_requests',forbidden)
    with pytest.raises(ValueError):assess(data)


@pytest.mark.parametrize('damage',['preparation_pin','registry_pin','reviews_pin','bindings_pin','clock','extra_cached'])
def test_malformed_dynamic_typed_inputs_preserve_hard_refusals(damage):
    data=material();params=data['response_calls'][1]['response_inputs']
    field={'preparation_pin':'expected_preparation_manifest_sha256','registry_pin':'expected_registry_sha256',
        'reviews_pin':'expected_reviews_sha256','bindings_pin':'expected_response_bindings_sha256'}.get(damage)
    if field:params[field]='0'*64
    elif damage=='clock':params['at_time_utc']='yesterday'
    else:params['raw_source_assessment']={'authenticated_evidence_count':2}
    if damage!='extra_cached':
        with pytest.raises(ValueError):old_assess(data,data['response_calls'][1])
    with pytest.raises(ValueError):assess(data)


@pytest.mark.parametrize('damage',['drop_row','reverse_rows','typed_count','variant','selected',
    'work','context','authority','mask','bool_mask'])
def test_rehashed_typed_report_changes_cannot_promote_or_remove_content(damage):
    data=material();report=assess(data);changed=deepcopy(report)
    if damage=='drop_row':changed['rows'].pop()
    elif damage=='reverse_rows':changed['rows'].reverse()
    elif damage=='typed_count':changed['rows'][1]['assessment']['counts']['authenticated_typed_responses']=0
    elif damage=='variant':changed['rows'][1]['assessment']['answer_variants'].pop()
    elif damage=='selected':changed['rows'][1]['assessment']['selected_occurrence']={'record_cid':'fixture:fake'}
    elif damage=='work':changed['work']['typed_response_content_checks']=0
    elif damage=='context':changed['bank_context_report']['projections'][0]['subject']['scope_id']='fixture:fake'
    elif damage=='authority':changed['authority'][next(iter(changed['authority']))]=True
    elif damage=='mask':changed['training_mask']=1
    else:changed['training_mask']=False
    with pytest.raises(ValueError):validate(changed,data)


@pytest.mark.parametrize('key',['max_original_bytes','max_json_nodes','max_context_bytes',
    'max_response_calls','max_response_input_bytes','max_response_evidence_bytes'])
def test_lower_typed_batch_caps_refuse_before_original_bank_work(key,monkeypatch):
    data=material()
    def forbidden(*args,**kwargs):raise AssertionError('lower typed cap must refuse before original replay')
    monkeypatch.setattr(legacy_review,'prepare_legacy_source_review_requests',forbidden)
    with pytest.raises(ValueError):assess(data,limits={key:1})


@pytest.mark.parametrize('key,value',[
    ('max_response_calls',True),('max_response_calls',129),
    ('max_response_input_bytes',True),('max_response_input_bytes',8388609),
    ('max_response_evidence_bytes',True),('max_response_evidence_bytes',8388609)])
def test_typed_caps_are_lower_only_plain_integers_before_original_work(key,value,monkeypatch):
    data=material()
    def forbidden(*args,**kwargs):raise AssertionError('invalid typed cap must refuse before original replay')
    monkeypatch.setattr(legacy_review,'prepare_legacy_source_review_requests',forbidden)
    with pytest.raises(ValueError):assess(data,limits={key:value})


@pytest.mark.parametrize('damage',['calls','originals','limits','detached_evidence','offered_report'])
def test_closing_fences_enclose_genuine_typed_content_work(damage,monkeypatch):
    data=material();limits={};offered=assess(data) if damage=='offered_report' else None
    original=legacy_responses._content;seen=[]
    def mutating(*args,**kwargs):
        result=original(*args,**kwargs);seen.append(1)
        if damage=='calls':data['response_calls'][0]['response_inputs']['response_bindings'][0]['raw_sha256']='0'*64
        elif damage=='originals':data['banks'][0]['join_inputs']['source_sections'][0]['text']+=' changed'
        elif damage=='limits':limits['max_response_input_bytes']=1
        elif damage=='detached_evidence':args[-1].clear()
        else:offered['training_mask']=1
        return result
    monkeypatch.setattr(legacy_responses,'_content',mutating)
    with pytest.raises(ValueError):
        if offered is None:assess(data,limits=limits)
        else:validate(offered,data,limits=limits)
    assert seen


@pytest.mark.parametrize('damage',['unknown_finding','ambiguous_resolved','missing_answer','reordered_answers',
    'deferred_slot','category','kind','unknown_field','missing_evidence','historical_proposal'])
def test_old_public_typed_record_refusals_match_retained_owner(damage):
    signed=auth_helper().signed_case(legacy_review);response=response_helper().declaration(signed)
    answer=response['answers'][0]
    if damage=='unknown_finding':answer['finding']['status']='proven'
    elif damage=='ambiguous_resolved':answer['finding']['status']='ambiguous'
    elif damage=='missing_answer':response['answers'].pop()
    elif damage=='reordered_answers':response['answers'][:2]=reversed(response['answers'][:2])
    elif damage=='deferred_slot':answer['slot_id']=signed['preparation']['subjects'][0]['deferred_review_slot_ids'][0]
    elif damage in {'category','kind'}:answer[damage]='unsupported'
    elif damage=='unknown_field':response['original_producer_occurrence_attested']=True
    elif damage=='missing_evidence':answer['evidence_refs']=[]
    else:response['occurrence_proposal']['status']='original_producer_occurrence_attested'
    with pytest.raises(ValueError):response_helper().record(frozen_old_response_owner(),signed,response)
    with pytest.raises(ValueError):response_helper().record(legacy_responses,signed,response)


def test_response_call_commitment_binds_exact_evidence_and_complete_dynamic_inputs():
    data=material();expected=calls_sha256(data['response_calls'])
    assert owner.shared_bank_source_response_calls_sha256(data['response_calls'])==expected
    changed=deepcopy(data['response_calls'])
    changed[1]['response_inputs']['evidence_artifacts']['fixture:legacy-source-declaration']+=b' changed'
    assert owner.shared_bank_source_response_calls_sha256(changed)==calls_sha256(changed)!=expected
    assert owner.shared_bank_source_response_calls_sha256(data['response_calls'])==expected


def test_real_retained_32_typed_slots_remain_missing_without_invented_credentials(tmp_path, monkeypatch):
    assert os.environ.get('LEGAL_SHARED_BANK_RESPONSES_ENROLLED') == '1', 'exact original admission required'
    assert os.environ.get('LEGAL_SHARED_BANK_RESPONSES_INPUTS') == str(REAL_INPUTS)
    root_ref = {'path': str(REAL_INPUTS), 'bytes': REAL_INPUTS_BYTES, 'sha256': REAL_INPUTS_SHA256}
    inputs = read_json(root_ref)
    assert inputs['schema'] == 'legal-shared-bank-responses-qualification-inputs/v1'
    prior_inputs = read_json(inputs['prior_inputs'])
    refs = prior_inputs['originals']
    declarations = read_json(refs['parent_declarations'])
    legacy_inputs = read_json(refs['legacy_inputs'])
    sections = read_json(refs['parent_sections'])
    row_pins = read_json(refs['parent_row_pins'])
    crosswalk = read_json(refs['crosswalk'])
    assert len(crosswalk['records']) == 16 and len(crosswalk['bundles']) == 2
    assert len(sections['source_sections']) == len(sections['expected_source_sections']) == 13
    assert sections['selected_row_ordinals'] == row_pins['row_ordinals'] == ORDINALS
    assert len(row_pins['expected_row_sha256s']) == 13 and len(row_pins['all_columns']) == 45
    source_oracles = []
    source_by_ordinal = {}
    for ordinal, section, expected, row_hash in zip(ORDINALS, sections['source_sections'],
            sections['expected_source_sections'], row_pins['expected_row_sha256s'], strict=True):
        assert {key: section[key] for key in expected} == expected
        assert expected['parquet_row_index'] == ordinal
        assert sha(section['text'].encode('utf-8')) == expected['text_sha256']
        key = physical_source_key(expected)
        source_id = 'sha256:' + sha(wire(key))
        source_oracles.append({'physical_section_id': source_id, 'physical_key': key,
            'text_sha256': expected['text_sha256'], 'text_utf8_bytes': len(section['text'].encode('utf-8')),
            'independently_retained_full_row_sha256': row_hash, 'full_raw_row_recomputed_here': False})
        source_by_ordinal[ordinal] = section
    banks, cache_oracles = [], []
    for declaration, supplied in zip(declarations['banks'], prior_inputs['banks'], strict=True):
        bank_id, manifest = supplied['bank_id'], supplied['manifest_path_in_repo']
        assert declaration['bank'] == bank_id
        original = legacy_inputs[manifest]
        cross_rows = [row for row in crosswalk['records'] if row['manifest_path_in_repo'] == manifest]
        assert len(cross_rows) == len(supplied['paired_rows']) == len(declaration['rows']) == 8
        raw_rows = [read_exact(ref) for ref in supplied['paired_rows']]
        physical_rows = []
        for ordinal, cross_row, row_raw, row_ref, expected in zip(range(8), cross_rows, raw_rows,
                supplied['paired_rows'], original['expected_population'], strict=True):
            assert cross_row['row_ordinal'] == ordinal
            assert cross_row['row_sha256'] == expected['row_sha256'] == row_ref['sha256'] == sha(row_raw)
            physical = {'repository_id': cross_row['repository_id'], 'revision': cross_row['revision'],
                'path_in_repo': cross_row['table']['path_in_repo'],
                'artifact_sha256': cross_row['table']['sha256'], 'row_ordinal': ordinal}
            published_key = {'repository_id': physical['repository_id'], 'revision': physical['revision'],
                'table_path_in_repo': physical['path_in_repo'], 'table_sha256': physical['artifact_sha256'],
                'row_ordinal': ordinal}
            assert cross_row['physical_record_id'] == 'sha256:' + sha(wire(published_key))
            physical_rows.append({'physical_row_ordinal': ordinal, 'request_ordinal': ordinal,
                                  'physical_identity': physical})
            cache_oracles.append({'bank_id': bank_id, 'physical_row_ordinal': ordinal,
                'physical_identity': physical, 'physical_record_id': cross_row['physical_record_id'],
                'reference_id': cross_row['reference_id'], 'paired_row_sha256': row_ref['sha256'],
                'candidate_occurrence_ids': cross_row['candidate_occurrence_ids']})
        receipt = read_exact(supplied['producer_receipt'])
        assert sha(receipt) == original['expected_producer_receipt_sha256']
        join_inputs = {key: deepcopy(original[key]) for key in ('expected_population',
            'expected_producer_receipt_sha256', 'source_sections', 'expected_source_sections')}
        join_inputs['producer_receipt_bytes'] = receipt
        for section in join_inputs['source_sections']:
            assert section == source_by_ordinal[section['parquet_row_index']]
        banks.append({'bank_id': bank_id, 'join_bytes': read_exact(supplied['join']),
            'paired_row_bytes': raw_rows, 'join_inputs': join_inputs, 'physical_rows': physical_rows})
    packet_raw = read_exact(inputs['packet']); packet = json.loads(packet_raw)
    assert packet_raw == wire(packet) + b'\n' and sha(wire(packet)) == inputs['packet_canonical_sha256']
    source_request_raw = read_exact(inputs['source_request'])
    assert source_request_raw == wire(json.loads(source_request_raw))
    assert json.loads(source_request_raw) == fixture_helper().request_for(banks)
    shared_raw = read_exact(inputs['shared_replay_report']); shared_report = json.loads(shared_raw)
    assert shared_raw == wire(shared_report) + b'\n'
    assert sha(wire(shared_report)) == inputs['shared_replay_report_canonical_sha256']
    replay_raw = read_exact(inputs['replay_request']); replay = json.loads(replay_raw)
    assert replay_raw == wire(replay) and replay == replay_request(banks, EPOCHS)
    data = {'banks': banks, 'packet': packet, 'source_request_raw': source_request_raw,
            'replay_request': replay, 'shared_report': shared_report}
    data['response_calls']=[{'epoch_id':row['epoch_id'],'bank_id':row['bank_id'],
        'request_ordinal':row['request_ordinal'],'response_inputs':None}
        for row in shared_report['schedule']['requests']]
    original=legacy_review.prepare_legacy_source_review_requests;actual_calls=[]
    def counted(*args,**kwargs):
        result=original(*args,**kwargs);actual_calls.append(sha(args[0]));return result
    monkeypatch.setattr(legacy_review,'prepare_legacy_source_review_requests',counted)
    def no_actual_trust(*args,**kwargs):
        raise AssertionError('missing actual evidence must not invoke or synthesize a trust assessment')
    monkeypatch.setattr(trust_owner,'_assess_reviews',no_actual_trust)
    monkeypatch.setattr(legacy_responses,'_content',no_actual_trust)
    report=assess(data)
    assert len(actual_calls)==2
    monkeypatch.setattr(legacy_review,'prepare_legacy_source_review_requests',original)
    assert validate(report,data)==report
    context=report['bank_context_report']
    assert context['shared_report']==shared_report
    assert context['coverage']=={'contexts_minted':2,'planned_epochs':2,'projected_logical_requests':32,
        'projected_physical_references':32,'projected_candidate_occurrence_references':300,
        'original_physical_references':16,'original_candidate_occurrence_references':150,
        'full_declared_population_retained':True}
    assert len(report['rows'])==32
    for row,call,projection in zip(report['rows'],data['response_calls'],context['projections'],strict=True):
        assert all(row[key]==call[key] for key in ('epoch_id','bank_id','request_ordinal'))
        assert row['assessment'] is None and row['assessment_status']=='not_assessed_missing_inputs'
        assert projection['request']['original_row']['selected_occurrence'] is None
    assert report['work']['source_bank_preparations']==2
    assert report['work']['fresh_source_assessments']==report['work']['fresh_typed_response_assessments']==0
    assert report['coverage']=={'planned_calls':32,'assessed_calls':0,'missing_input_calls':32,
        'physical_references':32,'candidate_occurrence_references':300,
        'full_declared_population_retained':True}
    assert report['work']=={'bank_context_prepare_calls':1,'source_bank_preparations':2,
        'private_preparation_capability_mints':2,'fresh_source_assessments':0,
        'fresh_fixed_domain_verifier_calls':0,'fresh_typed_response_assessments':0,
        'typed_response_content_checks':0,'source_bank_reparses_during_assessment':0,
        'history_epoch_replays':0,'authority_cache_hits':0}
    coverage=packet['coverage']
    assert coverage['banks']==2
    assert coverage['logical_requests']==coverage['physical_rows']==coverage['distinct_physical_identities']==16
    assert coverage['source_section_references']==coverage['distinct_source_sections']==13
    assert coverage['candidate_occurrence_references']==150
    assert coverage['unique_candidate_rows']==11 and coverage['ambiguous_candidate_rows']==5
    assert coverage['disposition_counts']=={'unique_exact_candidate':11,'ambiguous_exact_candidates':5}
    assert fixture_helper().assert_geometry(packet)==150
    names=('bank_id','physical_row_ordinal','physical_identity','paired_row_sha256','candidate_occurrence_ids')
    for physical,oracle in zip(packet['physical_rows'],cache_oracles,strict=True):
        assert {key:physical[key] for key in names}=={key:oracle[key] for key in names}
    assert sum(len(unit['context_slot_ids']) for bank in packet['banks'] for unit in bank['preparation']['requests'])==144
    assert sum(len(unit['deferred_review_slot_ids']) for bank in packet['banks'] for unit in bank['preparation']['requests'])==112
    flags(report);fixture_helper().no_authority(packet)
    def retain(name,raw):
        path=tmp_path/name
        assert len(raw)<=32*1024**2
        with path.open('xb') as stream:stream.write(raw)
        return {'path':str(path),**raw_ref(raw)}
    full_ref=retain('source-correspondence-full-report.json',wire(packet)+b'\n')
    source_ref=retain('source-correspondence-request.json',source_request_raw)
    shared_ref=retain('shared-source-replay-report.json',wire(shared_report)+b'\n')
    replay_ref=retain('shared-source-replay-request.json',replay_raw)
    context_ref=retain('shared-source-bank-context-report.json',wire(context)+b'\n')
    batch_ref=retain('shared-bank-source-response-report.json',wire(report)+b'\n')
    calls_raw=wire(data['response_calls'])
    calls_ref=retain('shared-bank-source-response-calls.json',calls_raw)
    evidence={'schema':'legal-shared-bank-responses-engineering-evidence/v1','coverage':coverage,
        'full_report':full_ref,'full_report_canonical_sha256':sha(wire(packet)),
        'request_sha256':sha(source_request_raw),'request_artifact':source_ref,
        'request_artifact_wire':'exact canonical compact sorted Unicode JSON API bytes without final LF',
        'shared_replay_report':shared_ref,'shared_replay_report_canonical_sha256':sha(wire(shared_report)),
        'replay_request_artifact':replay_ref,'replay_request_sha256':sha(replay_raw),
        'bank_context_report':context_ref,'bank_context_report_canonical_sha256':sha(wire(context)),
        'context_coverage':context['coverage'],'context_work':context['work'],
        'context_generation_sha256':context['context_generation_sha256'],
        'actual_prepare_bank_replay_calls':len(actual_calls),'actual_context_projection_count':32,
        'shared_bank_response_report':batch_ref,'shared_bank_response_report_canonical_sha256':sha(wire(report)),
        'response_calls_artifact':calls_ref,'response_calls_sha256':calls_sha256(data['response_calls']),
        'response_coverage':report['coverage'],'response_work':report['work'],
        'actual_fresh_source_assessments':0,'actual_fresh_typed_response_assessments':0,
        'actual_missing_response_inputs':32,'actual_typed_response_content_checks':0,
        'catalog_coverage':shared_report['catalog']['coverage'],'schedule_coverage':shared_report['schedule']['coverage'],
        'work':shared_report['work'],'scheduled_candidate_references':300,
        'original_input_refs':[root_ref]+inputs['productive_originals'],
        'physical_cache_oracles':cache_oracles,'retained_source_oracles':source_oracles,
        'exact_candidate_geometry_checked':150,'actual_submitted_reviews':0,
        'selected_occurrences':0,'source_decisions_applied':0,'actual_source_adoptions':0,
        'actual_history_epoch_replays':0,'planned_epochs_are_executed':False,
        'actual_saved_work_or_speedup_measured':False,'original_parent_or26shards_opened':False,
        'fresh_cache_table_verification':False,'fresh_full_raw_row_hash_recomputation':False,
        'correspondence_authority':packet['authority'],'shared_replay_authority':shared_report['authority'],
        'bank_context_authority':context['authority'],'authority':report['authority'],
        'training_mask':0,'evaluation_gold_mask':0,'inference_view':None,
        'worker_lifetime_peak_rss_linux_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_scope':'Linux worker lifetime peak includes bootstrap and fixtures; not an isolated owner peak or memory bound proof.'}
    assert len(evidence['original_input_refs'])==31
    with (tmp_path/EVIDENCE_NAME).open('xb') as stream:stream.write(wire(evidence)+b'\n')

