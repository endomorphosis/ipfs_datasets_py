"""Authored independent minimal contrasts for the bounded dependency veto."""
from copy import deepcopy
import pytest
from ipfs_datasets_py.logic.autoformal import legal_flat_scope_dependencies as dep
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition


def make(text,cuts=(),identity='opaque-case'):
    source={'candidate_id':identity,'source_text':text,'source_sha256':composition.text_sha256(text)}
    clauses=[];left=0
    for ordinal,right in enumerate((*cuts,len(text))):
        while left<right and text[left].isspace():left+=1
        end=right
        while end>left and text[end-1].isspace():end-=1
        clauses.append({'clause_id':f'occurrence-{ordinal}','char_start':left,'char_end':end,'scope':deepcopy(composition.FLAT_SCOPE)})
        left=right
    plan=composition.prepare_source_plan(source,clauses)
    return source,plan


def evaluate(text,cuts=()):
    source,plan=make(text,cuts)
    return dep.prepare_flat_scope_dependencies(source,plan,expected_plan_sha256=plan['plan_sha256'])


@pytest.mark.parametrize('text',[
    'Registry shall file notice.',
    'Registry may not release records.',
    'Registry is permitted to file notice.',
    'If the permit is active, Registry shall file notice.',
    'Unless the exemption is active, Registry shall file notice.',
    'Registry, when the permit is active, shall file notice.',
    'Registry shall, when the permit is active, file notice.',
    'Registry shall file notice if the permit is active.',
    'Registry shall file notice unless the exemption is active.',
    'Registry shall file notice except when the exemption is active.',
    'Within 3 days, Registry shall file notice.',
    'Registry shall file notice within 1.5 days.',
    'Before May 15, 2099, Registry shall file notice.',
    'The Dept. of Records shall file notice.',
    'Registry shall publish the notice "Board may archive unless exempt".',
    'Registry shall publish the notice “Board may archive.”.',
    "Registry shall publish the applicant's notice.",
    'Registry shall publish the applicant’s notice.',
])
def test_single_norm_local_qualifiers_and_protected_literals(text):
    result=evaluate(text)
    assert result['allows_flat_composition'],result['reasons']
    assert result['status']=='structurally_flat' and len(result['modal_nodes'])==1
    assert not result['semantic_independence_verified'] and not result['qualified']


@pytest.mark.parametrize('heading',['(2) Filing duty: ','Record duty [2]. ','Editorial index [section 63001.2]: ','Filing duty.— '])
def test_caption_before_actor_after_complete_local_condition(heading):
    text='If the permit is active, '+heading+'Registry shall file notice.'
    result=evaluate(text)
    assert result['allows_flat_composition'],result['reasons']
    assert any(row['kind']=='editorial_heading' for row in result['protected_spans'])


@pytest.mark.parametrize('separator',['. ', '; ', '.\n\n'])
def test_independent_qualified_norms_preserve_both_local_owners(separator):
    first='If the permit is active, Registry shall file notice unless the exemption is active'
    text=first+separator+'Unless the record is sealed, Board may archive the record.'
    result=evaluate(text,[len(first)+1])
    assert result['allows_flat_composition'],result['reasons']
    assert {q['owner_norm_id'] for q in result['qualifier_nodes']}=={'norm-00','norm-01'}
    assert not any(e['kind'].startswith('nested') for e in result['dependency_edges'])


@pytest.mark.parametrize('cue',['unless','except when','except where','if','when','provided that'])
def test_suffix_subordinate_norm_is_not_independent(cue):
    text=f'Registry shall file notice {cue} Board may archive the record.'
    result=evaluate(text)
    assert not result['allows_flat_composition']
    edge=next(e for e in result['dependency_edges'] if e['kind'].startswith('nested_'))
    assert (edge['owner_norm_id'],edge['child_norm_id'])==('norm-00','norm-01')


@pytest.mark.parametrize('cue',['If','Unless','Except when'])
def test_first_modal_can_be_subordinate_to_second_modal(cue):
    text=f'{cue} Board may archive the record, Registry shall file notice.'
    result=evaluate(text)
    assert not result['allows_flat_composition']
    edge=next(e for e in result['dependency_edges'] if e['kind'].startswith('nested_'))
    assert (edge['owner_norm_id'],edge['child_norm_id'])==('norm-01','norm-00')


@pytest.mark.parametrize('heading',['Filing duty.— ','Record duty [2]. ','Editorial index [section 63001.2]: '])
def test_caption_punctuation_cannot_launder_nested_exception_into_flat_cut(heading):
    prefix='Registry shall file notice unless '+heading
    text=prefix+'Board may archive the record.'
    # Supply the tempting but wrong source-complete cut at caption punctuation.
    cut=prefix.index('.')+1 if '.' in heading else len(prefix)
    result=evaluate(text,[cut])
    assert not result['allows_flat_composition']
    assert 'nested_normative_exception' in result['reasons']


def test_decimal_and_quote_cuts_defer_even_with_repaired_complete_plan():
    for text,needle in [('Editorial index [section 63001.2]: Registry shall file notice.','63001.'),
                        ('Registry shall publish "Board may archive." today.','archive.')]:
        cut=text.index(needle)+len(needle)
        result=evaluate(text,[cut])
        assert not result['allows_flat_composition'] and result['cut_findings']
        assert 'plan_cut_inside_protected_region' in result['reasons']


@pytest.mark.parametrize('text,reason',[
    ('If the permit is active: Registry shall file notice; Board may archive the record.','shared_preamble_or_unclassified_colon'),
    ('Registry shall file notice subject to section 63001.2.','unresolved_semantic_reference'),
    ('Registry shall file notice under section 63001.2.','unresolved_semantic_reference'),
    ('Registry shall file notice under such condition.','unresolved_cross_clause_context'),
    ('Registry shall publish "Board may archive.','unbalanced_quote'),
    ('Registry shall publish [unclosed notice.','unbalanced_bracket'),
    ('Registry shall publish [Board may archive].','unclassified_bracket_content'),
    ('Registry shall file notice unless Filing duty.—','dangling_qualifier'),
    ('If the permit is active Registry shall file notice.','unclosed_prefix_qualifier'),
    ('The permit is active.','segment_without_explicit_norm'),
    ('Shall file notice.','missing_explicit_surface_actor'),
    ('Registry shall.','missing_explicit_surface_predicate'),
])
def test_ambiguous_or_unresolved_syntax_defers_with_named_trace(text,reason):
    result=evaluate(text)
    assert not result['allows_flat_composition'] and reason in result['reasons'],result['reasons']


def test_time_in_condition_stays_owned_by_that_atom():
    result=evaluate('When the application arrived within 14 days, Registry shall file notice before 2099-03-14.')
    assert result['allows_flat_composition'],result['reasons']
    times=[q for q in result['qualifier_nodes'] if q['kind']=='temporal_lexeme']
    assert [t['attachment_status'] for t in times]==['inside_local_atom','local_declared_time']
    assert times[0]['owner_qualifier_id'] is not None and times[1]['owner_qualifier_id'] is None


def test_repeated_identical_rules_preserve_distinct_occurrences():
    unit='Registry shall file notice.';result=evaluate(unit+' '+unit,[len(unit)])
    assert result['allows_flat_composition'] and [m['node_id'] for m in result['modal_nodes']]==['norm-00','norm-01']
    assert result['modal_nodes'][0]['char_start']!=result['modal_nodes'][1]['char_start']


@pytest.mark.parametrize('mutation',['owner','cut','permission','scopeclaim','extra','source'])
def test_repaired_evidence_hash_cannot_change_authoritative_regeneration(mutation):
    source,plan=make('If permit active, Registry shall file notice.')
    value=dep.prepare_flat_scope_dependencies(source,plan,expected_plan_sha256=plan['plan_sha256'])
    changed=deepcopy(value)
    if mutation=='owner':changed['qualifier_nodes'][0]['owner_norm_id']='norm-99'
    if mutation=='cut':changed['recognized_top_level_intervals'][0][1]-=1
    if mutation=='permission':changed['allows_flat_composition']=False
    if mutation=='scopeclaim':changed['semantic_independence_verified']=True
    if mutation=='extra':changed['trusted']=True
    if mutation=='source':changed['source']['source_text']='Other text.'
    changed['evidence_sha256']=dep.digest({k:v for k,v in changed.items() if k!='evidence_sha256'})
    with pytest.raises(ValueError,match='authoritative regeneration'):
        dep.validate_flat_scope_dependencies(source,plan,changed,expected_plan_sha256=plan['plan_sha256'])


def test_external_plan_and_source_commitments_are_required():
    source,plan=make('Registry shall file notice.')
    wrong=deepcopy(source);wrong['candidate_id']='other'
    with pytest.raises(ValueError,match='authoritative source'):
        dep.prepare_flat_scope_dependencies(wrong,plan,expected_plan_sha256=plan['plan_sha256'])
    with pytest.raises(ValueError,match='external commitment'):
        dep.prepare_flat_scope_dependencies(source,plan,expected_plan_sha256='0'*64)
    with pytest.raises(ValueError,match='closed source'):
        dep.prepare_flat_scope_dependencies({**source,'canonical_ir':{}},plan,expected_plan_sha256=plan['plan_sha256'])


def test_id_is_not_a_lexical_feature_and_regeneration_is_exact():
    text='Registry shall file notice.';a,p=make(text,identity='unsupported-looking-id');b,q=make(text,identity='supported-looking-id')
    x=dep.prepare_flat_scope_dependencies(a,p,expected_plan_sha256=p['plan_sha256']);y=dep.prepare_flat_scope_dependencies(b,q,expected_plan_sha256=q['plan_sha256'])
    for key in ('status','allows_flat_composition','protected_spans','modal_nodes','qualifier_nodes','dependency_edges','reasons'):
        assert x[key]==y[key]
    assert dep.validate_flat_scope_dependencies(a,p,x,expected_plan_sha256=p['plan_sha256'])==x


def test_released_legacy_nested_failure_is_deferred_without_clause_predictions():
    text=('If the amberbirch231 permit is active, the Amberbirch231 Public Register Authority, within 37 hours, '
          'may not record the amberbirch231 filing packet unless Filing duty.— '
          'the Amberbirch232 Records Office shall transfer the amberbirch232 filing packet.')
    result=evaluate(text,[167])
    assert 'nested_normative_exception' in result['reasons']
    assert 'plan_cut_inside_protected_region' in result['reasons']
    assert not result['allows_flat_composition']


def test_nested_date_and_caption_cut_remains_deferred():
    text=('within 103 hours, Record duty [2]. the Registry is permitted to publish the filing packet except when '
          'Editorial index [section 63001.2]: except when the exemption is active, when the application was received '
          'before 2094-03-14, before 2099-09-14, the Dept. of Records must not record the filing packet.')
    result=evaluate(text,[text.index('63001.')+6])
    assert not result['allows_flat_composition']
    assert result['cut_findings'] and 'ambiguous_qualifier_attachment' in result['reasons']


def test_unknown_profile_and_bound_overflow_fail_closed():
    source,plan=make('Registry shall file notice.')
    with pytest.raises(ValueError,match='profile'):
        dep.prepare_flat_scope_dependencies(source,plan,expected_plan_sha256=plan['plan_sha256'],profile='general-English')
    source,plan=make('Registry shall '+('word '*245)+'notice. '+ 'Board may '+('word '*245)+'archive.',
                     [len('Registry shall '+('word '*245)+'notice.')])
    # The inherited clause bound is256; the dependency document cap is512.
    assert len(composition._TOKENS.findall(source['source_text']))<=512
    result=dep.prepare_flat_scope_dependencies(source,plan,expected_plan_sha256=plan['plan_sha256'])
    assert result['allows_flat_composition']


def test_ambiguous_multi_norm_attachments_do_not_invent_owner_edges():
    value=evaluate('Registry shall file unless Board may archive unless Council must inspect records.')
    assert not value['allows_flat_composition'] and 'ambiguous_multi_norm_attachment' in value['reasons']
    assert value['dependency_edges']==[]


def test_complete_local_atom_before_unseparated_second_norm_is_ambiguous():
    value=evaluate('Unless the exemption is active, Board may archive, Registry shall file notice.')
    assert not value['allows_flat_composition'] and 'ambiguous_qualifier_attachment' in value['reasons']
    assert value['dependency_edges']==[]


def test_document_token_bound_rejects_three_individually_bounded_clauses():
    unit='Registry shall '+('word '*180)+'file notice.'
    source,plan=make(unit+' '+unit+' '+unit,[len(unit),len(unit)*2+1])
    with pytest.raises(ValueError,match='profile bounds'):
        dep.prepare_flat_scope_dependencies(source,plan,expected_plan_sha256=plan['plan_sha256'])
