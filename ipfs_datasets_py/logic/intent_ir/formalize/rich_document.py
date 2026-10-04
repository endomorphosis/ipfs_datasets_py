"""Opt-in document routing for a versioned rich learned Intent checkpoint."""
from __future__ import annotations

from collections import Counter

from . import document_roundtrip as legacy
from . import rich_grammar as grammar
from .rich_decoder import prepare_rich_intent_instruction, wire, sha, CHECKPOINT_SCHEMA
from ...formalization.text_spans import source_selector

SCHEMA='intent-rich-document/v1'
CONTEXT_SCHEMA='intent-rich-document-context/v1'


def prepare_rich_intent_document(source_text, checkpoint_descriptor, *, start_char=0,end_char=None,
                                context=None,requested_families=None,lake_executable=None,
                                composition_recovery=True,beam_width=16,grammar_search_recovery=True):
    from ...families.registry import DEFAULT_REGISTRY
    from .rich_logic import validate_rich_intent_logic
    if type(source_text) is not str or not source_text or len(source_text.encode())>1048576:
        raise ValueError('bounded rich source document required')
    if type(checkpoint_descriptor) is not dict or checkpoint_descriptor.get('schema')!=CHECKPOINT_SCHEMA:
        raise ValueError('explicit rich checkpoint selection required')
    if type(composition_recovery) is not bool:
        raise ValueError('explicit boolean composition recovery required')
    if type(grammar_search_recovery) is not bool:
        raise ValueError('explicit boolean grammar search recovery required')
    if type(beam_width) is not int or not 0 <= beam_width <= 16:
        raise ValueError('bounded explicit rich document beam width required')
    end_char=len(source_text) if end_char is None else end_char
    selection=source_selector(source_text,start_char,end_char)
    families=sorted(DEFAULT_REGISTRY.families) if requested_families is None else requested_families
    if (type(families) not in (list,tuple) or not families or len(set(families))!=len(families)
            or any(x not in DEFAULT_REGISTRY.families for x in families)):
        raise ValueError('unique canonical rich family selection required')
    source_hash=sha(source_text.encode())
    contexts={}
    if context is not None:
        if (type(context) is not dict or set(context)!={'schema','source_sha256','checkpoint_sha256','units'}
                or context['schema']!=CONTEXT_SCHEMA or context['source_sha256']!=source_hash
                or context['checkpoint_sha256']!=sha(wire(checkpoint_descriptor))
                or type(context['units']) is not list or len(context['units'])>128):
            raise ValueError('closed source/checkpoint-bound rich context required')
        for item in context['units']:
            if (type(item) is not dict or set(item)!={'unit_id','clause_sha256','slot_context'}
                    or item['unit_id'] in contexts):
                raise ValueError('unique explicit rich unit context required')
            if item['slot_context'] is not None and 'higher_order' not in families:
                raise ValueError('rich slot context requires selected higher_order fixture')
            contexts[item['unit_id']]=item
    used_contexts=set()
    units,candidates,checks=[],[],[]
    counts=Counter({'units':0,'inference_attempts':0,'encoder_executions':0,'decoder_executions':0,
                    'accepted_clauses':0,'direct_accepted_clauses':0,'composed_accepted_clauses':0,
                    'grammar_searched_accepted_clauses':0,'grammar_search_attempts':0,
                    'composition_attempts':0,'lake_attempts':0,'lake_passes':0})
    available=set()
    for span in legacy._inventory(source_text):
        left,right=max(start_char,span['start_char']),min(end_char,span['end_char'])
        if left>=right:continue
        selector=source_selector(source_text,left,right)
        unit_id='intent-unit:'+sha(wire({'source_sha256':source_hash,'start_char':left,'end_char':right}))
        unit={'unit_id':unit_id,**selector,'accepted':False,'inference':None,'scope':None,
              'status':'unsupported_context_or_scope','reason':span['reason'],'selected_projections':[],
              'atomic_family_projection':None,'selected_native_targets':[]}
        complete=left==span['start_char'] and right==span['end_char']
        try:
            if not complete:raise ValueError('selection_splits_source_unit')
            if span['status']=='excluded':raise ValueError(span['reason'])
            if any(legacy._CONTEXT_MODAL.search(h['title']) for h in span['heading_context']):
                raise ValueError('modal_heading_requires_composition')
            if any(c['role'] in {'label','lead_in','parent_list','structural_unit'} for c in span['structural_context']):
                raise ValueError('structural_scope_requires_composition')
            instruction=span['normalized_text']
            admitted=grammar.parse_instruction(instruction)
            if span['status']!='candidate':
                reasons=set(span['block_context']['context_reasons'])
                allowed_reasons={'conditional_context','inline_code_context'}
                # The legacy span inventory treats "then" as an anaphor.
                # Only a fully admitted explicit two-clause sequence owns that
                # scope locally; a leading "Then" still lacks an antecedent.
                if admitted['kind']=='then':
                    from .skillcenter_spans import _ANAPHORA
                    # Retain the inventory's other anaphora exclusions inside
                    # both atoms (for example "next file" or "next agent").
                    if not any(_ANAPHORA.search(atom[field])
                            for atom in (admitted['left'],admitted['right'])
                            for field in ('actor','action','object')):
                        allowed_reasons.add('anaphoric_context')
                if (not reasons<=allowed_reasons or not reasons
                        or span['normalized_text']!=span['block_context']['normalized_text']):
                    raise ValueError('external_context_or_size_requires_composition')
            unit['scope']={'eligible_for_inference':True,'complete_source_consumption':True}
            if counts['inference_attempts']>=128:raise ValueError('rich_inference_unit_limit')
            slot_context=None
            if unit_id in contexts:
                item=contexts[unit_id]
                if item['clause_sha256']!=sha(instruction.encode()):raise ValueError('stale_rich_clause_context')
                slot_context=item['slot_context'];used_contexts.add(unit_id)
            counts['inference_attempts']+=1
            inference=prepare_rich_intent_instruction(instruction,checkpoint_descriptor,
                context=slot_context,beam_width=beam_width)
            if (grammar_search_recovery and beam_width and admitted['kind']=='atom'
                    and inference['rich_ir'] is None and inference['counts']['encoder_executions']>0):
                from .rich_search_decoder import prepare_searched_rich_intent
                counts['grammar_search_attempts']+=1
                inference=prepare_searched_rich_intent(instruction,checkpoint_descriptor,
                    context=slot_context,base_report=inference)
            if (composition_recovery and admitted['kind']!='atom' and inference['rich_ir'] is None
                    and inference['counts']['encoder_executions']>0):
                from .compositional_decoder import prepare_composed_rich_intent
                counts['composition_attempts']+=1
                inference=prepare_composed_rich_intent(instruction,checkpoint_descriptor,
                    context=slot_context,base_report=inference)
            unit['inference']=inference
            unit['decoding_method']=inference.get('decoding_method','direct_neural_roundtrip')
            for key,value in inference['counts'].items():counts[key]+=value
            unit['status']=inference['status'];unit['reason']=inference.get('reason',inference['status'])
            if inference['rich_ir'] is not None:
                selected=[p for p in inference['logic']['projections'] if p['family_id'] in families]
                # Native flat targets are safe only for one complete atom.
                # They must never erase a conditional, choice or conjunction.
                if inference['rich_ir']['ast']['kind']=='atom':
                    from .extended_projections import project_intent_families,DEFAULT_FAMILIES,ADDITIONAL_REQUIREMENTS
                    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
                    extensions=[f for f in families if f in {*DEFAULT_FAMILIES,*ADDITIONAL_REQUIREMENTS}]
                    native=inference['logic']['native_intent_ir']
                    if extensions:
                        bundle=project_intent_families(native,requested_families=extensions)
                        selected.extend(bundle['projections'])
                        targets=bundle['native_targets']['projections']
                    else:
                        bundle={'native_targets':prepare_intent_targets(native).to_dict(),'projections':[]}
                        targets=bundle['native_targets']['projections']
                    unit['atomic_family_projection']=bundle
                    unit['selected_native_targets']=[p for p in targets if p['logic_family'] in families]
                    available.update(p['logic_family'] for p in unit['selected_native_targets'])
                unit['selected_projections']=selected
                available.update(p['family_id'] for p in selected if p['status'] in {'projected','partial','candidate'})
                unit['accepted']=True
                method_counter={'grammar_composition_with_neural_leaves':'composed_accepted_clauses',
                    'grammar_constrained_neural_roundtrip':'grammar_searched_accepted_clauses'}
                counts[method_counter.get(unit['decoding_method'],'direct_accepted_clauses')]+=1
                candidates.append({'unit_id':unit_id,'start_char':left,'end_char':right,
                    'rich_ir':inference['rich_ir'],'inference_report_sha256':inference['report_sha256']})
                if lake_executable and 'higher_order' in families:
                    checked=validate_rich_intent_logic(inference['logic'],instruction=instruction,
                        ast=inference['rich_ir']['ast'],context=slot_context,lake_executable=lake_executable)
                    checks.append({'unit_id':unit_id,'receipt':checked})
                    counts['lake_attempts']+=bool(checked.get('backend_executed'))
                    counts['lake_passes']+=checked.get('status')=='passed'
        except (ValueError,TypeError) as exc:
            unit['reason']=str(exc)
        counts['units']+=1
        counts['status:'+unit['status']]+=1
        units.append(unit)
    if set(contexts)!=used_contexts:
        raise ValueError('rich context references an unselected or unsupported source unit')
    if ''.join(u['text'] for u in units)!=selection['text']:
        raise ValueError('rich source inventory must preserve every character')
    counts['accepted_clauses']=len(candidates)
    result={'schema':SCHEMA,'status':'partial_rich_candidates' if candidates else 'fail_open_no_supported_clauses',
        'projection_mode':'native_rich_checkpoint_views_with_explicit_family_selection',
        'composition_recovery':composition_recovery,
        'grammar_search_recovery':grammar_search_recovery,
        'beam_width':beam_width,
        'source_sha256':source_hash,'checkpoint_descriptor':checkpoint_descriptor,'selection':selection,
        'units':units,'candidates':candidates,'counts':dict(counts),'lake_checks':checks,
        'requested_families':families,'family_inventory':[{'family_id':f,
            'status':'available_views' if f in available else 'unsupported' if f in families else 'not_requested'}
            for f in sorted(DEFAULT_REGISTRY.families)],
        'raw_instruction_preserved':True,'training_steps':0,'llm_calls':0,'proof_authority':False,
        'execution_authority':False,'source_semantics_verified':False,'whole_document_formalized':False}
    result['report_sha256']=sha(wire(result))
    return result
