from copy import deepcopy
import pytest
from scripts.ops.legal_ir import summarize_legal_atom_boundary_experiment as q


def tensors():
    import torch
    logits=torch.tensor([[-2.,1.,-.3,.2,2.,-1.],[1.,-3.,.7,-.2,4.,2.],[1.,2.,3.,4.,5.,6.]],dtype=torch.float64,requires_grad=True)
    labels=torch.tensor([[0,0,1,0,1,0],[0,1,0,1,0,0],[1,0,0,0,0,0]],dtype=torch.float64)
    valid=torch.tensor([[1,1,1,1,1,0],[1,1,1,1,0,0],[1,1,1,0,0,0]],dtype=torch.bool)
    supported=torch.tensor([True,True,False]);positive=valid&supported[:,None]&labels.bool()
    editorial=torch.tensor([[0,1,0,0,0,0],[1,0,0,0,0,0],[0,0,0,0,0,0]],dtype=torch.bool)
    transition=torch.tensor([[0,0,1,0,0,0],[0,1,0,0,0,0],[0,0,0,0,0,0]],dtype=torch.bool)
    atom=torch.tensor([[1,0,0,1,0,0],[0,0,1,0,0,0],[0,0,0,0,0,0]],dtype=torch.bool)
    teacher=torch.tensor([[-1.,0.,0.,-2.,-1.,50.],[1.,2.,-1.,2.,80.,90.],[-4.,6.,-2.,5.,4.,8.]],dtype=torch.float64,requires_grad=True)
    return torch,logits,labels,valid,supported,positive,editorial,transition,atom,teacher


@pytest.mark.parametrize('arm',q.ARMS)
def test_full_objective_values_gradients_and_teacher_detachment_match_independent_oracle(arm):
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    torch,x,y,v,s,p,e,t,a,teacher=tensors()
    actual,parts=runtime.objective_loss(torch,x,y,v,s,p,e,t,a,teacher_logits=teacher,arm=arm)
    expected,oracle=q.atom_loss_oracle(torch,x,y,v,s,p,e,t,a,teacher_logits=teacher,arm=arm)
    ga,gt=torch.autograd.grad(actual,(x,teacher),retain_graph=True,allow_unused=True)
    ge,get=torch.autograd.grad(expected,(x,teacher),allow_unused=True)
    assert torch.allclose(actual,expected,atol=1e-12,rtol=1e-12) and torch.allclose(ga,ge,atol=1e-12,rtol=1e-12)
    assert gt is None and get is None and torch.count_nonzero(ga[~(v&s[:,None])])==0
    for key,value in oracle.items():
        if torch.is_tensor(value) and value.ndim>0:assert parts[key]==value.tolist()
        elif type(value) is bool:assert parts[key] is value
        else:assert parts[key]==pytest.approx(float(value),abs=1e-12)


@pytest.mark.parametrize('case',['both_classes','positive_only','negative_only','empty','zero_tie','saturated'])
def test_teacher_class_balancing_and_empty_mask_contract(case):
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    x=torch.tensor([[1.,2.,3.,4.]],dtype=torch.float64,requires_grad=True)
    y=torch.tensor([[1.,0.,0.,0.]],dtype=torch.float64);v=torch.ones_like(y,dtype=torch.bool);s=torch.tensor([True])
    values={'both_classes':[2.,-1.,-2.,-3.],'positive_only':[2.,1.,2.,3.],'negative_only':[-2.,-1.,-2.,-3.],'empty':[-2.,1.,2.,3.],'zero_tie':[0.,0.,0.,0.],'saturated':[1000.,-1000.,-1000.,-1000.]}
    teacher=torch.tensor([values[case]],dtype=torch.float64,requires_grad=True)
    actual,parts=runtime.teacher_token_kl(torch,x,y,v,s,teacher_logits=teacher)
    expected,oracle=q.teacher_kl_oracle(torch,x,y,v,s,teacher)
    ga,gt=torch.autograd.grad(actual,(x,teacher),retain_graph=True,allow_unused=True);ge=torch.autograd.grad(expected,x)[0]
    assert torch.allclose(actual,expected,atol=1e-12,rtol=1e-12) and torch.allclose(ga,ge,atol=1e-12,rtol=1e-12) and gt is None
    assert parts['teacher_available_class_count']=={'both_classes':2,'positive_only':1,'negative_only':1,'empty':0,'zero_tie':1,'saturated':2}[case]
    if case=='empty':assert float(actual)==0 and torch.count_nonzero(ga)==0
    if case=='zero_tie':assert parts['teacher_positive_mask']==[[True,False,False,False]] and parts['teacher_correct_negative_count']==0
    if case=='both_classes':
        assert float(actual)==pytest.approx(.5*(parts['teacher_positive_kl_sum']+parts['teacher_negative_kl_sum']/3))
        assert abs(float(actual)-(parts['teacher_positive_kl_sum']+parts['teacher_negative_kl_sum'])/4)>.001


def test_randomized_oracle_hundred_tensors_and_gradients():
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    torch,_,y,v,s,p,e,t,a,_=tensors();rng=torch.Generator().manual_seed(130427)
    for i in range(100):
        x=(torch.randn(y.shape,dtype=torch.float64,generator=rng)*9).requires_grad_();teacher=torch.randn(y.shape,dtype=torch.float64,generator=rng)*9
        arm=q.ARMS[i%3];actual,_=runtime.objective_loss(torch,x,y,v,s,p,e,t,a,teacher_logits=teacher,arm=arm)
        expected,_=q.atom_loss_oracle(torch,x,y,v,s,p,e,t,a,teacher_logits=teacher,arm=arm)
        ga=torch.autograd.grad(actual,x,retain_graph=True)[0];ge=torch.autograd.grad(expected,x)[0]
        # Runtime softplus switches to its linear approximation above20;
        # the independent log-partition oracle retains the exponentially small term.
        assert torch.allclose(actual,expected,atol=1e-9,rtol=1e-12) and torch.allclose(ga,ge,atol=1e-9,rtol=1e-12)


@pytest.mark.parametrize('mutation',['terminal','missing_transition','unsupported_atom','padding_atom','gold_atom','empty_atom','gap_validity','teacher_nan','teacher_shape','nonbinary_gold'])
def test_invalid_masks_and_teacher_tensors_fail_closed(mutation):
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    torch,x,y,v,s,p,e,t,a,teacher=tensors()
    if mutation=='terminal':t[0,4]=True
    if mutation=='missing_transition':t[0,2]=False
    if mutation=='unsupported_atom':a[2,1]=True
    if mutation=='padding_atom':a[0,5]=True
    if mutation=='gold_atom':a[0,2]=True
    if mutation=='empty_atom':a[:]=False
    if mutation=='gap_validity':v[0,3]=False;a[0,3]=False
    if mutation=='teacher_nan':teacher=teacher.detach().clone();teacher[0,0]=float('nan')
    if mutation=='teacher_shape':teacher=teacher[:,:-1]
    if mutation=='nonbinary_gold':y[0,0]=.5
    with pytest.raises(ValueError):q.atom_loss_oracle(torch,x,y,v,s,p,e,t,a,teacher_logits=teacher,arm='distill')
    with pytest.raises(ValueError):runtime.objective_loss(torch,x,y,v,s,p,e,t,a,teacher_logits=teacher,arm='distill')


def atom_fixture():
    text='The Records Board [A] shall retain the file before 2035-06-07. Filing duty [2]. The Review Office may inspect the file unless the waiver [B] is valid.'
    boundary=text.index('. Filing')+1
    clauses=[{'char_start':0,'char_end':boundary,'rule':{'actor':'The Records Board [A]','temporal':['before 2035-06-07'],'exceptions':[]}},
        {'char_start':boundary+1,'char_end':len(text),'rule':{'actor':'The Review Office','temporal':[],'exceptions':['the waiver [B] is valid']}}]
    row={'candidate_id':'scope-'+q.boundary.text_sha(text),'source_text':text,'source_sha256':q.boundary.text_sha(text),'supported':True,'clauses':clauses}
    spans=[]
    for kind,literal in [('actor','The Records Board [A]'),('temporal','before 2035-06-07'),('actor','The Review Office'),('exceptions','the waiver [B] is valid')]:
        start=text.index(literal);spans.append({'kind':kind,'char_start':start,'char_end':start+len(literal)})
    tokens=q.boundary.tokenize(text);gold=[i for i,t in enumerate(tokens) if t['char_end'] in {c['char_end'] for c in clauses}]
    interior=[i for i,t in enumerate(tokens) if i not in gold and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in spans)]
    record={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'inter_clause_end_token_indices':gold[:-1],'atom_interior_negative_token_indices':interior,'atom_spans':spans,'provenance':'pinned_supported_train_atoms_and_inter_clause_endpoints/v1'}
    return row,record


def test_atom_masks_include_words_numbers_and_punctuation_but_not_editorial_heading_or_terminal():
    row,record=atom_fixture();transition,interior=q.atom_role_masks(row,record);tokens=q.boundary.tokenize(row['source_text'])
    values=[t['text'] for t,yes in zip(tokens,interior,strict=True) if yes]
    assert sum(transition)==1 and not transition[-1] and not interior[-1]
    assert 'Records' in values and '[' in values and '2035' in values and '-' in values and 'waiver' in values
    assert 'Filing' not in values and 'duty' not in values


@pytest.mark.parametrize('mutation',['inflated_span','wrong_role','drop_word','punctuation_only','terminal_positive','missing_interclause','source_hash','provenance','ambiguous_atom'])
def test_repaired_atom_indices_cannot_override_authoritative_canonical_roles(mutation):
    row,record=atom_fixture()
    if mutation=='inflated_span':record['atom_spans'][0]['char_end']=row['source_text'].index('retain')+len('retain')
    if mutation=='wrong_role':record['atom_spans'][0]['kind']='exceptions'
    if mutation=='drop_word':record['atom_interior_negative_token_indices'].pop(0)
    if mutation=='punctuation_only':record['atom_interior_negative_token_indices']=[i for i in record['atom_interior_negative_token_indices'] if q.re.fullmatch(r'[^\w\s]',q.boundary.tokenize(row['source_text'])[i]['text'])]
    if mutation=='terminal_positive':record['inter_clause_end_token_indices'].append(len(q.boundary.tokenize(row['source_text']))-1)
    if mutation=='missing_interclause':record['inter_clause_end_token_indices']=[]
    if mutation=='source_hash':record['source_sha256']='a'*64
    if mutation=='provenance':record['provenance']='model_mined'
    if mutation=='ambiguous_atom':row['clauses'][0]['rule']['actor']='the'
    if mutation in ('inflated_span','wrong_role'):
        tokens=q.boundary.tokenize(row['source_text']);gold={c['char_end'] for c in row['clauses']}
        record['atom_interior_negative_token_indices']=[i for i,t in enumerate(tokens) if t['char_end'] not in gold and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in record['atom_spans'])]
    with pytest.raises(ValueError):q.atom_role_masks(row,record)


def scored(identity,supported,raw=False,delivered=False,accepted=False):
    return {'id':identity,'source_sha256':q.boundary.text_sha(identity),'supported':supported,'raw_interval_exact':raw,'delivered_interval_exact':delivered,'status':'segmented' if accepted or delivered else 'abstained','delivered_intervals':[[0,4]] if accepted or delivered else None}


def metrics(rows):
    supported=[r for r in rows if r['supported']];unsupported=[r for r in rows if not r['supported']]
    return {'count':len(rows),'supported':len(supported),'unsupported':len(unsupported),'raw_supported_correct':len(supported),'raw_unsupported_accepted':len(unsupported),'raw_boundary_exact':sum(r['raw_interval_exact'] for r in supported),'supported_exact':sum(r['delivered_interval_exact'] for r in supported),'unsupported_accepted':sum(r['delivered_intervals'] is not None for r in unsupported)}


def gate_fixture():
    old=[scored('s1',True,True,True),scored('s2',True),scored('s3',True),scored('u1',False,accepted=True),scored('u2',False),scored('u3',False)]
    candidate=deepcopy(old);candidate[1]=scored('s2',True,True,True)
    parents={'atom_new':metrics(old),'history':metrics(old)}
    stages=[{'steps':step,'metrics':{p:metrics(candidate) for p in parents},'churn':{p:q.churn_from_scored_rows(old,candidate) for p in parents},'raw_scope_logits_unchanged':True} for step in q.STAGES]
    return old,candidate,parents,stages


def test_new_unsupported_acceptance_rejected_even_when_count_unchanged():
    old,candidate,parents,stages=gate_fixture();candidate[3]=scored('u1',False);candidate[4]=scored('u2',False,accepted=True)
    for stage in stages:
        stage['metrics']['history']=metrics(candidate);stage['churn']['history']=q.churn_from_scored_rows(old,candidate)
    assert stages[0]['metrics']['history']['unsupported_accepted']==parents['history']['unsupported_accepted']
    assert stages[0]['churn']['history']['unsupported']['newly_accepted_ids']==['u2']
    assert q.boundary_choice(stages,parents) is None


def test_rejecting_more_old_unsupported_accepts_is_allowed_without_requiring_zero_parent_errors():
    old,candidate,parents,stages=gate_fixture();assert q.boundary_choice(stages,parents)['steps']==100
    candidate[3]=scored('u1',False)
    for stage in stages:
        stage['metrics']['history']=metrics(candidate);stage['churn']['history']=q.churn_from_scored_rows(old,candidate)
    assert q.boundary_choice(stages,parents)['steps']==100


def test_supported_churn_reports_offsetting_losses_without_inventing_strict_identity_gate():
    old,candidate,parents,stages=gate_fixture();candidate[0]=scored('s1',True);candidate[2]=scored('s3',True,True,True)
    churn=q.churn_from_scored_rows(old,candidate)
    assert churn['raw_supported']['won_ids']==['s2','s3'] and churn['raw_supported']['lost_ids']==['s1'] and churn['raw_supported']['net_change']==1
    for stage in stages:stage['metrics']['history']=metrics(candidate);stage['churn']['history']=churn
    assert q.boundary_choice(stages,parents)['steps']==100


@pytest.mark.parametrize('mutation',['omit_source','duplicate_source','source_hash','class','status','unsupported_gold'])
def test_source_churn_cannot_drop_or_relabel_failures(mutation):
    old,candidate,_,_=gate_fixture()
    if mutation=='omit_source':candidate.pop()
    if mutation=='duplicate_source':candidate.append(deepcopy(candidate[0]))
    if mutation=='source_hash':candidate[0]['source_sha256']='b'*64
    if mutation=='class':candidate[-1]['supported']=True
    if mutation=='status':candidate[0]['status']='abstained'
    if mutation=='unsupported_gold':candidate[-1]['raw_interval_exact']=True
    with pytest.raises(ValueError):q.churn_from_scored_rows(old,candidate)


@pytest.mark.parametrize('mutation',['hidden_new_accept','duplicate_winner','missing_loss','wrong_count','scope_flag','raw_regression'])
def test_gate_receipt_tampering_fails_or_rejects(mutation):
    _,_,parents,stages=gate_fixture()
    for stage in stages:
        if mutation=='hidden_new_accept':stage['churn']['history']['unsupported']['newly_accepted_ids']=['u2']
        if mutation=='duplicate_winner':stage['churn']['history']['raw_supported']['won_ids']*=2
        if mutation=='missing_loss':stage['churn']['history']['raw_supported']['retained_exact_ids']=[]
        if mutation=='wrong_count':stage['metrics']['history']['count']+=1
        if mutation=='scope_flag':stage['raw_scope_logits_unchanged']=False
        if mutation=='raw_regression':stage['metrics']['history']['raw_boundary_exact']=0
    if mutation=='scope_flag':assert q.boundary_choice(stages,parents) is None
    else:
        with pytest.raises(ValueError):q.boundary_choice(stages,parents)


def receipt_fixture():
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    row,atom=atom_fixture();tokens=q.boundary.tokenize(row['source_text']);ends={c['char_end'] for c in row['clauses']}
    start=row['source_text'].index('Filing duty');stop=row['source_text'].index('The Review Office')
    heading={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],
        'true_end_token_indices':[i for i,t in enumerate(tokens) if t['char_end'] in ends],
        'editorial_hard_negative_token_indices':[i for i,t in enumerate(tokens) if start<=t['char_start']<t['char_end']<=stop and q.re.fullmatch(r'[^\w\s]',t['text'])],
        'editorial_heading_spans':[{'char_start':start,'char_end':stop}], 'provenance':'pinned_train_endpoints_and_optional_editorial_spans/v1'}
    y,p,e=q.heading.training_role_masks(row,heading);transition,interior=q.atom_role_masks(row,atom)
    rows=[];headings={};atoms={}
    for i in range(12):
        identity=f'train-fixture-{i}';r=deepcopy(row);r['candidate_id']=identity;rows.append(r)
        headings[identity]={**deepcopy(heading),'candidate_id':identity};atoms[identity]={**deepcopy(atom),'candidate_id':identity}
    labels=torch.tensor([y]*12);valid=torch.ones_like(labels,dtype=torch.bool);supported=torch.ones(12,dtype=torch.bool)
    positive,negative,t,a=[torch.tensor([mask]*12) for mask in (p,e,transition,interior)]
    logits=torch.linspace(-2.,3.,labels.numel()).reshape(labels.shape);teacher=labels*2-1
    loss,parts=runtime.objective_loss(torch,logits,labels,valid,supported,positive,negative,t,a,teacher_logits=teacher,arm='distill')
    record={'candidate_logits':logits.tolist(),'labels':labels.tolist(),'valid_mask':valid.tolist(),'supported':supported.tolist(),
        'positive_mask':positive.tolist(),'negative_mask':negative.tolist(),'transition_mask':t.tolist(),'atom_mask':a.tolist(),
        'objective_components':parts,'total_loss':float(loss)}
    return record,rows,headings,atoms,teacher.tolist(),float(loss)


def test_actual_batch_teacher_and_authoritative_roles_bind_complete_loss_receipt():
    record,rows,headings,atoms,teacher,loss=receipt_fixture()
    assert q.verify_loss_receipt(record,rows,headings,atoms,teacher_logits=teacher,arm='distill',loss=loss)


@pytest.mark.parametrize('mutation',['teacher_repaired_hash','teacher_mask','teacher_count','teacher_reduction','teacher_weight','teacher_direction_flag','atom_mask','transition_terminal','atom_weight','total','boolean_mask'])
def test_repaired_receipt_hash_cannot_hide_teacher_provenance_or_atom_supervision_changes(mutation):
    record,rows,headings,atoms,teacher,loss=receipt_fixture();parts=record['objective_components']
    if mutation=='teacher_repaired_hash':parts['teacher_token_logits'][0][0]+=.2;parts['teacher_token_logits_sha256']=q.digest(parts['teacher_token_logits'])
    if mutation=='teacher_mask':parts['teacher_correct_mask'][0][0]=False
    if mutation=='teacher_count':parts['teacher_available_class_count']=1
    if mutation=='teacher_reduction':parts['teacher_class_average']='all_tokens'
    if mutation=='teacher_weight':parts['teacher_kl_weight']=1.
    if mutation=='teacher_direction_flag':parts['teacher_logits_detached']=False
    if mutation=='atom_mask':record['atom_mask'][0][0]=not record['atom_mask'][0][0]
    if mutation=='transition_terminal':record['transition_mask'][0][-1]=True
    if mutation=='atom_weight':parts['atom_auxiliary_weight']=0.
    if mutation=='total':parts['total_loss']+=.1;record['total_loss']=parts['total_loss'];loss=record['total_loss']
    if mutation=='boolean_mask':record['valid_mask'][0][0]=1
    with pytest.raises(ValueError):q.verify_loss_receipt(record,rows,headings,atoms,teacher_logits=teacher,arm='distill',loss=loss)


def test_three_pool_schedule_matches_root_sampler_through_multiple_epoch_wraps():
    from scripts.ops.legal_ir import run_legal_atom_boundary_experiment as runner
    replay=[{'candidate_id':f'old-{i}','supported':True} for i in range(7)]
    headings=[{'candidate_id':f'heading-{i}','supported':True} for i in range(9)]
    atoms=[{'candidate_id':f'atom-{i}','supported':True} for i in range(10)]
    pairs=[{'pair_id':f'p{i}','forward_id':f'atom-{2*i}','rotated_id':f'atom-{2*i+1}','local_clause_body_sha256':['a','b']} for i in range(5)]
    expected=list(runner.batch_schedule(replay,headings,atoms,pairs));actual=q.matched_batches(replay,headings,pairs)
    assert actual==[receipt for _,receipt in expected] and len(actual)==400
    assert all([r['candidate_id'] for r in rows]==receipt['common_replay_ids']+receipt['heading_ids']+receipt['atom_ids'] for rows,receipt in expected)


def endpoint_fixture():
    row,role=atom_fixture();tokens=q.boundary.tokenize(row['source_text']);gold=[i for i,t in enumerate(tokens) if t['char_end'] in {c['char_end'] for c in row['clauses']}]
    local=[]
    for clause in row['clauses']:
        spans={kind:next(([s['char_start'],s['char_end']] for s in role['atom_spans'] if s['kind']==kind and clause['char_start']<=s['char_start']<s['char_end']<=clause['char_end']),None) for kind in ('actor','temporal','exceptions')}
        local.append({'facet_spans':spans,'editorial_context':[]})
    left=row['source_text'].index('Filing duty');right=row['source_text'].index('The Review Office');local[1]['editorial_context']=[{'start_char':left,'end_char':right}]
    annotation={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'factors':{'child_structure':'fictional'},'local_clause_coordinates':local}
    prediction={'candidate_id':row['candidate_id'],'source_sha256':row['source_sha256'],'boundary_logits':[1. if i in gold else -1. for i in range(len(tokens))],'boundary_token_indices':gold,'raw_learned_scope_supported':False}
    unsupported=deepcopy(row);unsupported['source_text']+=' Unless';unsupported['source_sha256']=q.boundary.text_sha(unsupported['source_text']);unsupported['candidate_id']='scope-'+unsupported['source_sha256'];unsupported['supported']=False;unsupported['clauses']=[]
    ua={**deepcopy(annotation),'candidate_id':unsupported['candidate_id'],'source_sha256':unsupported['source_sha256']};width=len(q.boundary.tokenize(unsupported['source_text']))
    up={'candidate_id':unsupported['candidate_id'],'source_sha256':unsupported['source_sha256'],'boundary_logits':[1.]*width,'boundary_token_indices':list(range(width)),'raw_learned_scope_supported':True}
    rows=[row,unsupported];sources=[{k:r[k] for k in ('candidate_id','source_text','source_sha256')} for r in rows]
    return {'rows':[prediction,up]},sources,rows,[annotation,ua],role


def test_endpoint_diagnostics_keep_scope_abstentions_separate_atom_and_terminal_errors():
    generation,sources,targets,annotations,role=endpoint_fixture();result=q.atom_endpoint_diagnostics(generation,sources,targets,annotations)
    assert result['metrics']['documents']==2 and result['metrics']['supported_documents']==1 and result['metrics']['unsupported_without_endpoint_gold']==1
    assert result['metrics']['raw_endpoint_exact']==1 and result['metrics']['inter_clause_gold_ends']==1 and result['metrics']['terminal_gold_ends']==1
    assert result['metrics']['atom_interior_tokens']==sum(v['tokens'] for v in result['by_atom'].values())
    assert result['rows'][1]['endpoint_error_scored'] is False and 'atom_false_ends' not in result['rows'][1]
    p=generation['rows'][0];wrong=role['atom_interior_negative_token_indices'][0];p['boundary_logits'][wrong]=0.;p['boundary_logits'][-1]=-1.;p['boundary_token_indices']=sorted(i for i,x in enumerate(p['boundary_logits']) if x>=0)
    changed=q.atom_endpoint_diagnostics(generation,sources,targets,annotations)
    assert changed['metrics']['atom_false_ends']==1 and changed['by_atom']['actor']['false_ends']==1
    assert changed['metrics']['terminal_missed_ends']==1 and changed['metrics']['inter_clause_missed_ends']==0


@pytest.mark.parametrize('mutation',['drop_source','source_hash','threshold','overlapping_atom'])
def test_atom_endpoint_diagnostics_cannot_lose_denominators_or_change_roles(mutation):
    generation,sources,targets,annotations,_=endpoint_fixture()
    if mutation=='drop_source':generation['rows'].pop()
    if mutation=='source_hash':annotations[0]['source_sha256']='a'*64
    if mutation=='threshold':generation['rows'][0]['boundary_token_indices']=[]
    if mutation=='overlapping_atom':annotations[0]['local_clause_coordinates'][0]['facet_spans']['temporal']=annotations[0]['local_clause_coordinates'][0]['facet_spans']['actor']
    with pytest.raises(ValueError):q.atom_endpoint_diagnostics(generation,sources,targets,annotations)


def test_new_guard_acceptance_is_rejected_even_when_total_false_accepts_decrease():
    old,candidate,_,_=gate_fixture();old[4]=scored('u2',False,accepted=True);candidate[3]=scored('u1',False);candidate[4]=scored('u2',False);candidate[5]=scored('u3',False,accepted=True)
    parent={'atom_new':metrics(old)};churn=q.churn_from_scored_rows(old,candidate)
    stages=[{'steps':step,'metrics':{'atom_new':metrics(candidate)},'churn':{'atom_new':churn},'raw_scope_logits_unchanged':True} for step in q.STAGES]
    assert churn['unsupported']['count_change']==-1 and churn['unsupported']['newly_accepted_ids']==['u3']
    assert q.boundary_choice(stages,parent) is None


def test_teacher_disagreement_and_unsupported_tokens_receive_no_distillation_gradient():
    torch,x,y,v,s,_,_,_,_,teacher=tensors();loss,parts=q.teacher_kl_oracle(torch,x,y,v,s,teacher)
    gradient=torch.autograd.grad(loss,x)[0];correct=parts['teacher_correct_mask']
    assert torch.count_nonzero(gradient[~correct])==0 and torch.count_nonzero(gradient[correct])>0


def test_os_guard_denies_current_reference_until_explicit_release(tmp_path):
    import subprocess,sys
    target=tmp_path/'current-reference.json';target.write_text('{}')
    program='''import sys\nfrom scripts.ops.legal_ir import summarize_legal_atom_boundary_experiment as q\np=sys.argv[1];guard=q.SealedReadGuard([q.ref(p)]);sys.addaudithook(guard.event)\ntry:open(p).read()\nexcept (ValueError,RuntimeError,PermissionError):pass\nelse:raise AssertionError("premature reference read succeeded")\nassert len(guard.events)==1 and not guard.events[0]["after_build_freeze"]\nguard.released=True\nassert open(p).read()=="{}" and guard.events[-1]["after_build_freeze"]\n'''
    result=subprocess.run([sys.executable,'-c',program,str(target)],cwd=q.ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
