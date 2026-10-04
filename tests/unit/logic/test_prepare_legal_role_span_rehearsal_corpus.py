"""Direct coordinate, complementary sampling, occurrence and IO contracts."""
from collections import Counter
from copy import deepcopy
import builtins
import json
from pathlib import Path
import pytest
from scripts.ops.legal_ir import prepare_legal_role_span_rehearsal_corpus as c


@pytest.fixture(scope='module')
def inventory():
    return c.make_panels()


def test_counts_and_exact_modality_optional_mask_balance(inventory):
    panels,pairs,blocks,ledger=inventory
    assert {k:len(v) for k,v in panels.items()}==c.COUNTS
    assert len(blocks)==144 and len(ledger['single_rows'])==960 and len(ledger['document_rows'])==192
    for panel in ('train','tuning','fresh'):
        rows=panels[panel]
        assert Counter((r['canonical_ir']['rules'][0]['modality'],c.presence_mask(r)) for r in rows)=={(m,k):len(rows)//24 for m in 'OPF' for k in range(8)}
        assert len(pairs[panel])==len(rows)//2


def test_pair_full_canonical_identity_and_exhaustive_membership(inventory):
    panels,pairs,_,_=inventory
    for panel in ('train','tuning','fresh'):
        rows={r['id']:r for r in panels[panel]};seen=[]
        for pair in pairs[panel]:
            assert set(pair)==c.PAIR_KEYS
            left,right=rows[pair['left_id']],rows[pair['right_id']]
            assert left['canonical_ir']==right['canonical_ir']
            assert left['source_text']!=right['source_text']
            seen.extend((left['id'],right['id']))
        assert len(seen)==len(set(seen))==len(rows)


def test_each_block_two_present_two_absent_all_optional_roles(inventory):
    panels,pairs,blocks,_=inventory;rows={r['id']:r for r in panels['train']};pm={p['pair_id']:p for p in pairs['train']}
    for block in blocks:
        assert set(block)==c.BLOCK_KEYS
        chosen=[rows[pm[p][side]] for p in block['pair_ids'] for side in ('left_id','right_id')]
        assert len({r['id'] for r in chosen})==4
        for f in c.FIELDS[3:]:assert sum(bool(r['canonical_ir']['rules'][0][f]) for r in chosen)==2
    assert len({p for b in blocks for p in b['pair_ids']})==288


@pytest.mark.parametrize('mutation',['duplicate_pair','noncomplement','unknown_pair','extra_key'])
def test_malformed_auxiliary_blocks_rejected(inventory,mutation):
    panels,pairs,blocks,_=inventory;bad=deepcopy(blocks)
    if mutation=='duplicate_pair':bad[1]['pair_ids']=bad[0]['pair_ids']
    elif mutation=='noncomplement':bad[0]['pair_ids'][1]=bad[1]['pair_ids'][0]
    elif mutation=='unknown_pair':bad[0]['pair_ids'][1]='missing'
    else:bad[0]['side']='target'
    with pytest.raises(ValueError):c.validate_blocks(panels['train'],pairs['train'],bad)


@pytest.mark.parametrize('field',c.FIELDS)
def test_all_source_spans_bind_exact_author_atoms(inventory,field):
    panels,_,_,_=inventory
    for panel in ('train','tuning','fresh'):
        for row in panels[panel]:
            value=row['canonical_ir']['rules'][0][field];span=row['facet_spans'][field]
            if isinstance(value,list):value=value[0] if value else None
            assert (span is None)==(value is None)
            if span:assert row['source_text'][slice(*span)]==value


def test_caption_exclusion_and_real_lexical_actor_traps(inventory):
    panels,_,_,ledger=inventory;rows={r['id']:r for r in panels['train']};labels=[a for a in ledger['single_rows'] if a['panel']=='train']
    assert sum(not a['editorial_context'] for a in labels)==72
    assert Counter(a['caption_style'] for a in labels)=={0:192,1:192,2:192}
    assert any('Filing Duty Office' in r['canonical_ir']['rules'][0]['actor'] for r in rows.values())
    assert any('Record Duty Authority' in r['canonical_ir']['rules'][0]['actor'] for r in rows.values())
    after_qualifiers=0
    for a in labels:
        row=rows[a['id']]
        for note in a['editorial_context']:
            lo,hi=note['start_char'],note['end_char']
            assert row['source_text'][lo:hi]==note['source_text']
            assert all(span is None or span[1]<=lo or span[0]>=hi for span in row['facet_spans'].values())
            after_qualifiers+=any(span and span[1]<=lo for f,span in row['facet_spans'].items() if f in c.FIELDS[3:])
    assert after_qualifiers>100


def test_all_cues_appear_at_front_infix_and_suffix_in_train(inventory):
    panels,_,_,ledger=inventory;rows={r['id']:r for r in panels['train']}
    positions={cue:set() for cue in c.temporal.CONDITION_CUES+c.temporal.EXCEPTION_CUES}
    for a in ledger['single_rows']:
        if a['panel']!='train':continue
        row=rows[a['id']]
        for cue in a['qualifier_cues']:
            p=cue['start_char'];kind='front' if p<row['facet_spans']['actor'][0] else 'suffix' if p>row['facet_spans']['object'][1] else 'infix'
            positions[cue['source_text'].strip()].add(kind)
    assert all(value=={'front','infix','suffix'} for value in positions.values())


def test_time_absence_can_contain_condition_owned_time(inventory):
    panels,_,_,ledger=inventory;rows={r['id']:r for r in panels['train']}
    selected=[a for a in ledger['single_rows'] if a['panel']=='train' and a['condition_owned_temporal_language']]
    assert selected
    for a in selected:
        row=rows[a['id']];rule=row['canonical_ir']['rules'][0]
        assert not rule['temporal'] and row['facet_spans']['temporal'] is None
        assert ' days of publication' in rule['conditions'][0]
        assert row['source_text'][slice(*row['facet_spans']['conditions'])]==rule['conditions'][0]


def test_actual_layout_matches_and_collapses_are_not_universal_novelty(inventory):
    panels,_,_,_=inventory;known={c.temporal.role_layout(r) for r in panels['train']+panels['tuning']}
    matches=[c.temporal.role_layout(r) in known for r in panels['fresh']]
    assert any(matches) and not all(matches)
    absent=[r for r in panels['fresh'] if c.presence_mask(r)==0]
    assert all(c.temporal.role_layout(r) in known for r in absent)


def test_split_sources_cases_and_meanings_are_isolated(inventory):
    panels,pairs,blocks,ledger=inventory;result=c.validate_panels(panels,pairs,blocks,ledger)
    assert result['case_groups']==576
    assert result['cross_split_source_overlap']==result['cross_split_meaning_overlap']==result['cross_split_case_overlap']==0
    assert result['shared_grammar'] and not result['all_layouts_novel_claimed']


def test_document_counts_nested_pairs_and_repeated_occurrences(inventory):
    panels,pairs,_,ledger=inventory
    for panel in ('document_tuning','document_fresh'):
        rows=panels[panel];labels=[a for a in ledger['document_rows'] if a['panel']==panel]
        c.validate_document_pairs(rows,pairs[panel],labels)
        assert Counter(r['supported'] for r in rows)=={True:48,False:48}
        assert Counter(len(r['clauses']) for r in rows if r['supported'])=={2:24,3:24}
        assert sum(r['repeated_rule_occurrences'] for r in rows)==6
        assert all('provided that' not in r['source_text'] for r in rows)
        pack=c.oracle_pack(rows,labels)
        assert len(pack['targets'])==120 and len(pack['boundaries'])==len(pack['document_sources'])==48
        assert len({r['id'] for r in pack['targets']})==120
        assert len({r['source_text'] for r in pack['targets']})==114
        assert all(v['status']=='planned' for v in pack['boundaries'])


def test_oracle_substrings_occurrences_and_complete_plans(inventory):
    panels,_,_,ledger=inventory;rows=panels['document_tuning'];pack=c.oracle_pack(rows,[a for a in ledger['document_rows'] if a['panel']=='document_tuning'])
    documents={r['candidate_id']:r for r in rows}
    for source,item,target in zip(pack['sources'],pack['occurrences'],pack['targets'],strict=True):
        assert set(source)=={'id','source_text'} and set(item)==c.OCCURRENCE_KEYS
        assert source['id']==item['id']==target['id']
        assert source['source_text']==documents[item['document_id']]['source_text'][item['char_start']:item['char_end']]
        assert source['source_text'].endswith('.')
    for b in pack['boundaries']:
        plan=b['source_plan'];c.compose.validate_source_plan(plan,expected_plan_sha256=plan['plan_sha256'])
        assert all(clause['clause_id'].startswith('oracle-') for clause in plan['clauses'])


@pytest.mark.parametrize('mutation',['drop_document','offset','source_hash','reorder','missing_occurrence'])
def test_oracle_tampering_fails_closed(inventory,mutation):
    panels,_,_,ledger=inventory;pack=c.oracle_pack(panels['document_tuning'],[a for a in ledger['document_rows'] if a['panel']=='document_tuning'])
    if mutation=='drop_document':pack['document_sources'].pop()
    elif mutation=='offset':pack['occurrences'][0]['char_start']+=1
    elif mutation=='source_hash':pack['occurrences'][0]['source_sha256']='0'*64
    elif mutation=='reorder':pack['occurrences'][:2]=reversed(pack['occurrences'][:2])
    else:pack['occurrences'].pop();pack['sources'].pop()
    with pytest.raises((ValueError,KeyError)):
        c.validate_oracle_pack(pack['document_sources'],pack['sources'],pack['occurrences'],pack['boundaries'])


def test_runtime_dedup_retains_all_occurrence_provenance(inventory):
    panels,_,_,ledger=inventory;pack=c.oracle_pack(panels['document_tuning'],[a for a in ledger['document_rows'] if a['panel']=='document_tuning'])
    unique,provenance=c.deduplicate_runtime_tuning({'oracle':pack['targets']})
    assert len(unique)==len(provenance)==114 and sum(len(v['occurrences']) for v in provenance)==120
    assert sum(len(v['occurrences'])==2 for v in provenance)==6


def test_runtime_dedup_rejects_conflicting_same_text_labels(inventory):
    row=deepcopy(inventory[0]['tuning'][0]);other=deepcopy(row);other['id']='oracle-other';other['trigger_span'][0]+=1
    with pytest.raises(ValueError,match='conflicting'):c.deduplicate_runtime_tuning({'a':[row],'b':[other]})


def test_sources_are_class_neutral_hashes_and_shuffled(inventory):
    panels,_,_,_=inventory
    for panel in ('train','tuning','fresh'):
        rows=panels[panel]
        assert all(r['id']=='role-'+c.sha(r['source_text'].encode()) for r in rows)
        assert len({r['canonical_ir']['rules'][0]['modality'] for r in rows[:12]})>1
    for panel in ('document_tuning','document_fresh'):
        assert all(r['candidate_id']=='document-'+c.sha(r['source_text'].encode()) for r in panels[panel])
        assert {r['supported'] for r in panels[panel][:10]}=={True,False}


def test_deterministic_producer_output(inventory):
    assert c.make_panels()==inventory


def test_current_fresh_oracle_and_labels_are_separate_loader_phases():
    # This static contract test is paired with the actual guarded loader test
    # below; fresh oracle metadata intentionally reveals supplied segmentation.
    assert 'fresh_oracle_targets' in c.SEALED
    assert set(c.EVALUATION_ONLY)=={'fresh_oracle_sources','fresh_oracle_occurrences','fresh_oracle_boundaries','fresh_oracle_document_sources'}
    import inspect
    source=inspect.getsource(c.load_training_inputs)
    assert 'fresh_oracle_' not in source


def test_loader_never_opens_current_sealed_or_oracle_paths(tmp_path,monkeypatch,inventory):
    panels,pairs,blocks,ledger=inventory
    packs={p:c.oracle_pack(panels['document_tuning'],[a for a in ledger['document_rows'] if a['panel']=='document_tuning'])
           for p in ('new','atom_tuning','atom_fresh','prior_condition')}
    # Fictional historical rows occupy disjoint source groups. No current real
    # fresh-reference file is opened by this unit fixture or the loader.
    oldrow=c.temporal.render('train',c.temporal.FAMILIES[0],0,0,0)[0]
    oldlegacy={'training':[oldrow],'tuning':{},'retention_targets':{}}
    olddocs={k:panels['document_tuning'] for k in ('atom_tuning','atom_fresh','prior_condition')}
    oldpacks={k:packs[k] for k in olddocs}
    artifacts={}
    def save(k,v):
        p=tmp_path/(k+'.json');p.write_text(json.dumps(v));artifacts[k]=c.file_ref(p)
    for k,v in {'aux_rows':panels['train'],'aux_pairs':pairs['train'],'aux_blocks':blocks,
        'new_tuning':panels['tuning'],'tuning_pairs':pairs['tuning'],'document_tuning':panels['document_tuning'],
        'document_tuning_pairs':pairs['document_tuning'],
        'fresh_sources':[c.source_row(r) for r in panels['fresh']],
        'fresh_document_sources':[c.document_source(r) for r in panels['document_fresh']],
        'document_tuning_sources':[c.document_source(r) for r in panels['document_tuning']],
        'training_annotation_ledger':{'single_rows':[a for a in ledger['single_rows'] if a['panel']=='train'],'document_rows':[]},
        'tuning_annotation_ledger':{'single_rows':[a for a in ledger['single_rows'] if a['panel']=='tuning'],'document_rows':[a for a in ledger['document_rows'] if a['panel']=='document_tuning']},
        **{'oracle_'+kind:{p:v[kind] for p,v in packs.items()} for kind in ('sources','targets','occurrences','boundaries','document_sources')}
    }.items():save(k,v)
    for key in c.SEALED+c.EVALUATION_ONLY:save(key,{'never':'opened'})
    manifest={'artifacts':artifacts,'inputs':{'legacy_config':{'path':'fictional'},'prior_atom_corpus':{'path':'fictional'}},
              'main_training_sha256':c.digest(oldlegacy['training']),'main_training_rows':4080}
    monkeypatch.setattr(c,'_manifest',lambda _:manifest)
    monkeypatch.setattr(c,'historical_inputs',lambda *_:(oldlegacy,{},[],olddocs,oldpacks))
    forbidden={Path(artifacts[k]['path']).resolve() for k in c.SEALED+c.EVALUATION_ONLY};original=Path.read_bytes;attempts=[]
    def guarded(path):
        if path.resolve() in forbidden:attempts.append(str(path));raise AssertionError('sealed read')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',guarded)
    result=c.load_training_inputs('fictional')
    assert not attempts and len(result['aux_rows'])==576 and len(result['runtime_tuning'])==306
    assert sum(len(p['occurrences']) for p in result['runtime_tuning_provenance'])==192+480
