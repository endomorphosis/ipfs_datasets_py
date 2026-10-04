"""A declared, source-only structural veto for flat legal-rule composition.

This recognizer does not establish legal independence. It checks a bounded
surface grammar against an already supplied complete source plan. Quoted
literals, explicit editorial caption forms, locators, dates and listed
abbreviations retain exact offsets. Qualifiers must attach locally to one
normative modal; nested normative qualifiers and unresolved contexts defer.
The original learned boundary, scope and clause models are never altered.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from . import legal_rule_list_composition as composition

SCHEMA = 'legal-flat-scope-dependency-evidence/v1'
PROFILE = 'declared-local-flat-surface-grammar/v1'
MAX_SOURCE_BYTES = 40000
MAX_TOKENS = 512
MAX_NORMS = 8
FALSE = {'semantic_independence_verified': False, 'independent_scope_verified': False, 'source_semantics_verified': False,
         'statutory_scope_verified': False, 'qualified': False, 'admitted': False,
         'proof_authority': False, 'training_executed': False, 'model_inference_executed': False}
MODAL = re.compile(r'\b(?:is\s+(?:required|permitted|allowed)\s+to|must\s+not|shall\s+not|may\s+not|shall|must|may)\b', re.I)
QUALIFIER = re.compile(r'\b(?:except\s+when|except\s+where|provided\s+that|unless|if|when)\b', re.I)
TEMPORAL = re.compile(r'\b(?:within\s+\d+(?:\.\d+)?\s+(?:days?|hours?)|(?:before|after|by|on)\s+(?:\d{4}-\d{2}-\d{2}|May\s+\d{1,2}(?:,\s*\d{4})?))\b', re.I)
ABBREVIATION = re.compile(r'\b(?:U\.S\.C\.|U\.S\.|Dept\.|Sec\.|No\.|Co\.|Corp\.|Inc\.|Ltd\.|Jr\.|Sr\.|Art\.)', re.I)
DECIMAL = re.compile(r'\b\d+(?:\.\d+)+\b')
MAY_DATE = re.compile(r'\bMay\s+\d{1,2}(?:,\s*\d{4})?\b')
REFERENCE = re.compile(r'\b(?:section|subsection|paragraph|chapter)\s+\d|\b(?:subject\s+to|pursuant\s+to|as\s+defined\s+in|in\s+accordance\s+with)\b', re.I)
ANAPHORA = re.compile(r'\b(?:the\s+foregoing|as\s+above|such\s+(?:condition|exception|requirement)|following\s+(?:rules|requirements))\b', re.I)
HEADING_PATTERNS = (
    re.compile(r'\(\d{1,3}\)\s+[A-Z][A-Za-z -]{0,60}:\s*'),
    re.compile(r'\b[A-Z][A-Za-z]*(?:\s+[A-Za-z]+){0,5}\s+\[\d{1,3}\]\.\s*'),
    re.compile(r'\b[A-Z][A-Za-z]*(?:\s+[A-Za-z]+){0,5}\s+\[section\s+\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*\]:\s*', re.I),
    re.compile(r'\b[A-Z][A-Za-z]*(?:\s+[A-Za-z]+){1,5}\.\s*[—–]\s*'),
)

def digest(value):
    return composition.digest(value)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pins():
    return composition.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    _require(_pins() == _IMPORTED_PINS, 'flat dependency recognizer source changed since import')
    return dict(_IMPORTED_PINS)


def _node(text, kind, start, end, **extra):
    return {'kind': kind, 'char_start': start, 'char_end': end, 'source_text': text[start:end], **extra}


def _mask(text, spans):
    chars = list(text)
    for span in spans:
        chars[span['char_start']:span['char_end']] = ' ' * (span['char_end']-span['char_start'])
    return ''.join(chars)


def _trim(text, start, end):
    while start < end and text[start].isspace(): start += 1
    while end > start and text[end-1].isspace(): end -= 1
    return start, end


def _protect(text):
    """Protect only declared lexical forms; never remove source characters."""
    spans, reasons = [], []
    index = 0
    while index < len(text):
        char = text[index]
        apostrophe = char == "'" and index > 0 and index+1 < len(text) and text[index-1].isalnum() and text[index+1].isalnum()
        if char in ('"', '“', "'", '‘') and not apostrophe:
            closer = {'“':'”', '‘':'’'}.get(char, char)
            cursor = index+1
            while cursor < len(text):
                if text[cursor] == closer and (cursor == 0 or text[cursor-1] != '\\'):
                    if closer == "'" and cursor+1 < len(text) and text[cursor-1].isalnum() and text[cursor+1].isalnum():
                        cursor += 1; continue
                    break
                cursor += 1
            if cursor == len(text):
                reasons.append('unbalanced_quote'); break
            spans.append(_node(text, 'quoted_literal', index, cursor+1)); index = cursor+1
        elif char in ('”','’') and not (char=='’' and index>0 and index+1<len(text) and text[index-1].isalnum() and text[index+1].isalnum()):
            reasons.append('unbalanced_quote'); index += 1
        else:
            index += 1
    for pattern in HEADING_PATTERNS:
        masked = _mask(text, spans)
        # Overlapping candidates matter: a greedy title candidate may begin at
        # an earlier norm/cue. Reject that candidate without hiding the shorter
        # explicit caption that follows it (e.g. 'unless Filing duty.—').
        candidates = re.finditer('(?=(' + pattern.pattern + '))', masked, pattern.flags)
        for match in candidates:
            start,end = _trim(text,*match.span(1))
            if any(start < span['char_end'] and span['char_start'] < end for span in spans):
                continue
            if not MODAL.search(text[start:end]) and not QUALIFIER.search(text[start:end]):
                spans.append(_node(text, 'editorial_heading', start, end))
    masked = _mask(text, spans)
    stack = []
    for index,char in enumerate(masked):
        if char == '[': stack.append(index)
        elif char == ']':
            if not stack: reasons.append('unbalanced_bracket'); continue
            start = stack.pop()
            if stack: reasons.append('nested_bracket_outside_profile'); continue
            literal = text[start+1:index]
            if re.fullmatch(r'(?:section\s+)?\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*',literal,re.I):
                spans.append(_node(text,'locator',start,index+1))
            else: reasons.append('unclassified_bracket_content')
    if stack: reasons.append('unbalanced_bracket')
    for kind,pattern in (('abbreviation',ABBREVIATION),('decimal',DECIMAL),('month_date',MAY_DATE)):
        for match in pattern.finditer(_mask(text,spans)):
            spans.append(_node(text,kind,*match.span()))
    return sorted(spans,key=lambda s:(s['char_start'],s['char_end'],s['kind'])),reasons


def _segments(text, masked):
    result=[];start=0
    for match in re.finditer(r'[.!?;]|\n\s*\n',masked):
        left,right=_trim(text,start,match.end())
        if left<right: result.append((left,right))
        start=match.end()
    left,right=_trim(text,start,len(text))
    if left<right:result.append((left,right))
    return result


def _recognized(source,plan):
    text=source['source_text'];protected,reasons=_protect(text);masked=_mask(text,protected)
    modal_nodes=[];qualifier_nodes=[];edges=[];cuts=[];segments=_segments(text,masked)
    reference_text=_mask(text,[p for p in protected if p['kind'] in ('quoted_literal','editorial_heading')])
    if REFERENCE.search(reference_text):reasons.append('unresolved_semantic_reference')
    if ANAPHORA.search(masked):reasons.append('unresolved_cross_clause_context')
    # Colons outside a declared editorial caption do not close a local atom.
    if ':' in masked:reasons.append('shared_preamble_or_unclassified_colon')
    for clause in plan['clauses']:
        for name in ('char_start','char_end'):
            cut=clause[name]
            for span in protected:
                if span['char_start']<cut<span['char_end']:
                    cuts.append({'clause_id':clause['clause_id'],'cut_kind':name,'offset':cut,
                                 'protected_kind':span['kind'],'protected_span':[span['char_start'],span['char_end']]})
    if cuts:reasons.append('plan_cut_inside_protected_region')
    recognized_intervals=[]
    for ordinal,(left,right) in enumerate(segments):
        fragment=masked[left:right];modals=list(MODAL.finditer(fragment));cues=list(QUALIFIER.finditer(fragment))
        local=[]
        for match in modals:
            identity=f'norm-{len(modal_nodes):02d}'
            node=_node(text,'normative_modal',left+match.start(),left+match.end(),node_id=identity,
                       segment_ordinal=ordinal,segment_span=[left,right])
            modal_nodes.append(node);local.append(node)
        if not local:
            reasons.append('segment_without_explicit_norm');continue
        if len(local)>1:
            reasons.append('multiple_norms_without_independent_separator')
            if len(local)>2:
                reasons.append('ambiguous_multi_norm_attachment');continue
            for cue in cues:
                pos=left+cue.start();after=[m for m in local if m['char_start']>pos];before=[m for m in local if m['char_end']<=pos]
                if not after:continue
                child=after[0]
                closing_comma=masked.find(',',left+cue.end(),child['char_start'])
                if closing_comma>=0:
                    # A completed local atom may precede an unseparated norm;
                    # do not invent a unique dependency edge for that case.
                    reasons.append('ambiguous_qualifier_attachment');continue
                if before:
                    owner=before[-1]
                else:
                    # Prefix subordinate norm: its closing comma must precede the parent modal.
                    following=[m for m in local if m['char_start']>child['char_end']]
                    comma=masked.find(',',child['char_end'],right)
                    owner=next((m for m in following if 0<=comma<m['char_start']),None)
                if owner is not None:
                    kind='exception' if cue.group().lower().startswith(('unless','except')) else 'condition'
                    qid=f'qualifier-{len(qualifier_nodes):02d}'
                    qualifier_nodes.append(_node(text,kind,pos,left+cue.end(),node_id=qid,
                      owner_norm_id=owner['node_id'],attachment_status='nested_normative_dependency',atom_span=None))
                    edges.append({'kind':'nested_'+kind,'owner_norm_id':owner['node_id'],'child_norm_id':child['node_id'],
                                  'qualifier_id':qid})
                    reasons.append('nested_normative_'+kind)
            continue
        norm=local[0];recognized_intervals.append([left,right]);local_qualifiers=[]
        for position,cue in enumerate(cues):
            start,end=left+cue.start(),left+cue.end()
            following=left+cues[position+1].start() if position+1<len(cues) else right
            comma=masked.find(',',end,min(following,right))
            atom_end=comma if comma>=0 else following
            if start<norm['char_start'] and (comma<0 or comma>norm['char_start']):
                reasons.append('unclosed_prefix_qualifier');atom_end=min(atom_end,norm['char_start'])
            atom_start,atom_end=_trim(text,end,atom_end)
            while atom_end>atom_start and text[atom_end-1] in '.;!?':atom_end-=1
            if atom_start>=atom_end or not re.search(r'\w',masked[atom_start:atom_end]):reasons.append('dangling_qualifier')
            kind='exception' if cue.group().lower().startswith(('unless','except')) else 'condition'
            qid=f'qualifier-{len(qualifier_nodes):02d}'
            node=_node(text,kind,start,end,node_id=qid,owner_norm_id=norm['node_id'],
                       attachment_status='local_declared_atom',atom_span=[atom_start,atom_end])
            qualifier_nodes.append(node);local_qualifiers.append(node)
            edges.append({'kind':'local_'+kind,'owner_norm_id':norm['node_id'],'qualifier_id':qid})
        for match in TEMPORAL.finditer(text,left,right):
            start,end=match.span()
            if any(p['kind'] in ('quoted_literal','editorial_heading') and p['char_start']<=start<p['char_end'] for p in protected):continue
            # A time phrase within an already complete C/E atom stays owned by that atom.
            owner=next((q for q in local_qualifiers if q['atom_span'][0]<=start and end<=q['atom_span'][1]),None)
            qid=f'qualifier-{len(qualifier_nodes):02d}'
            node=_node(text,'temporal_lexeme',start,end,node_id=qid,owner_norm_id=norm['node_id'],
                       attachment_status='inside_local_atom' if owner else 'local_declared_time',
                       owner_qualifier_id=owner['node_id'] if owner else None,atom_span=[start,end])
            qualifier_nodes.append(node)
            edges.append({'kind':'time_inside_atom' if owner else 'local_time','owner_norm_id':norm['node_id'],
                          'qualifier_id':qid,'owner_qualifier_id':owner['node_id'] if owner else None})
        # Verify a surface actor and predicate remain outside local qualifier atoms.
        erased=[{'char_start':q['char_start'],'char_end':q['atom_span'][1]} for q in local_qualifiers]
        erased += [{'char_start':q['char_start'],'char_end':q['char_end']} for q in qualifier_nodes
                   if q['owner_norm_id']==norm['node_id'] and q['kind']=='temporal_lexeme' and q['attachment_status']=='local_declared_time']
        surface=_mask(masked,erased)
        if not re.search(r'[A-Za-z]',surface[left:norm['char_start']]):reasons.append('missing_explicit_surface_actor')
        if not re.search(r'[A-Za-z]',surface[norm['char_end']:right]):reasons.append('missing_explicit_surface_predicate')
    if not 1<=len(modal_nodes)<=MAX_NORMS:reasons.append('norm_count_outside_profile')
    plan_intervals=[[row['char_start'],row['char_end']] for row in plan['clauses']]
    if recognized_intervals!=plan_intervals:
        reasons.append('plan_cuts_do_not_match_complete_top_level_norms')
    return protected,modal_nodes,qualifier_nodes,edges,cuts,sorted(set(reasons)),recognized_intervals


def prepare_flat_scope_dependencies(source,source_plan,*,expected_plan_sha256,profile=PROFILE):
    """Recompute structural attachment evidence from complete authoritative text.

    ``allows_flat_composition`` is only a veto result under this declared grammar.
    It never authorizes a new learned cut or establishes statutory independence.
    """
    _require(profile==PROFILE,'explicit supported dependency profile required')
    source=composition._source(source)
    _require(len(source['source_text'].encode())<=MAX_SOURCE_BYTES and
             len(composition._TOKENS.findall(source['source_text']))<=MAX_TOKENS,'source exceeds dependency profile bounds')
    plan=composition.validate_source_plan(source_plan,expected_plan_sha256=expected_plan_sha256)
    _require(plan['source']==source,'source plan differs from authoritative source')
    protected,modals,qualifiers,edges,cuts,reasons,intervals=_recognized(source,plan)
    value={'schema':SCHEMA,'profile':PROFILE,'source':deepcopy(source),'source_sha256':source['source_sha256'],
      'source_plan_sha256':expected_plan_sha256,'status':'deferred' if reasons else 'structurally_flat',
      'allows_flat_composition':not reasons,'protected_spans':protected,'modal_nodes':modals,
      'qualifier_nodes':qualifiers,'dependency_edges':edges,'cut_findings':cuts,'reasons':reasons,
      'recognized_top_level_intervals':intervals,'producer_pins':producer_pins(),
      'claim':'Declared surface-grammar consistency only; absence of recognized dependencies is not verified semantic independence.',
      'source_id_used_as_feature':False,'canonical_formulas_or_reference_labels_used':False,**FALSE}
    value['evidence_sha256']=digest(value)
    return deepcopy(value)


def validate_flat_scope_dependencies(source,source_plan,evidence,*,expected_plan_sha256):
    _require(type(evidence) is dict,'closed dependency evidence required')
    expected=prepare_flat_scope_dependencies(source,source_plan,expected_plan_sha256=expected_plan_sha256)
    _require(composition._wire(evidence)==composition._wire(expected),'dependency evidence differs from authoritative regeneration')
    return expected
