#!/usr/bin/env python3
"""Post-qualification paired case-cluster comparisons of clause training policies.

Only complete reference exactness is compared. Compiler success never determines
correctness. Resampling retains all paraphrases and three fixed seeds within each
case; intervals are conditional on these authored cases and selected checkpoints.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import analyze_legal_temporal_curriculum as bootstrap

SEEDS=(1729,1730,1731)
ARCHITECTURES=('continuation','grounding')
POLICIES=('parent','ce','consistency')
BOUNDARIES=('parent','expanded')
COMPARISONS=(('ce','parent'),('consistency','parent'),('consistency','ce'))
SCHEMA='legal-clause-consistency-paired-analysis/v1'


def require(condition,message):
    if not condition:raise ValueError(message)


def ref(path):
    path=Path(path).resolve();data=path.read_bytes()
    return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def read_ref(reference):
    actual=ref(reference['path'])
    require(actual['sha256']==reference['sha256'] and ('bytes' not in reference or actual['bytes']==reference['bytes']),'artifact hash or byte size differs')
    return json.loads(Path(reference['path']).read_bytes())


def binding(recorded,actual):
    require(recorded['path']==actual['path'] and recorded['sha256']==actual['sha256'],'qualification binding differs')
    return read_ref(recorded)


def qualified_inputs(run_directory,qualification_directory):
    """The build/summary gate precedes all annotation or reference access."""
    run=Path(run_directory).resolve();q=Path(qualification_directory).resolve()
    require((q/'summary.json').is_file() and (q/'builds-frozen.json').is_file(),'completed qualification and build freeze required before labels')
    summary_ref=ref(q/'summary.json');summary=read_ref(summary_ref)
    require(summary.get('schema')=='legal-clause-consistency-independent-qualification/v1','completed consistency qualification required')
    require(summary.get('fresh_target_and_regression_references_opened_after_replay_and_build_freezes') is True
        and summary.get('test_results_used_for_selection_or_gate_revision') is False,'post-build reference access and fixed selection confirmation required')
    frozen_ref=ref(run/'generation-frozen.json');build_ref=ref(q/'builds-frozen.json')
    frozen=binding(summary['generation_freeze'],frozen_ref);builds=binding(summary['builds'],build_ref)
    require(builds.get('fresh_and_regression_targets_opened') is False,'native build freeze must precede label access')
    require(frozen.get('all_training_selection_and_generation_complete') is True
        and frozen.get('fresh_targets_opened') is frozen.get('regression_targets_opened') is False,'complete source-only generation freeze required')
    plan=read_ref(frozen['plan']);config=read_ref(plan['config']);manifest=read_ref(config['corpus_manifest'])
    require(manifest.get('schema')=='legal-clause-consistency-corpus/v1','consistency corpus manifest required')
    ledger_ref=manifest['artifacts']['annotation_ledger']
    require(summary['posthoc_evidence']['annotation_ledger']==ledger_ref,'qualified annotation ledger binding differs')
    sources=read_ref(frozen['sources'])['fresh'];document_sources=read_ref(frozen['document_sources'])['fresh_documents']
    # Only completed qualification can reach reference-derived annotation bytes.
    ledger=read_ref(ledger_ref);details=read_ref(summary['details'])
    return {'summary':summary,'summary_ref':summary_ref,'frozen':frozen,'frozen_ref':frozen_ref,
        'build_ref':build_ref,'manifest':manifest,'ledger':ledger,'ledger_ref':ledger_ref,'details':details,
        'sources':sources,'document_sources':document_sources}


def memberships(ledger,sources,document_sources,families):
    require(ledger.get('schema')=='legal-clause-consistency-annotations/v1','consistency annotation schema required')
    fresh=[a for a in ledger['single_rows'] if a['panel']=='fresh']
    singles={a['id']:a for a in fresh};docs={a['candidate_id']:a for a in ledger['document_rows']}
    require(len(fresh)==len(singles)==len(sources)==144 and set(singles)=={r['id'] for r in sources},'complete144 fresh single annotation/source slots required')
    require(len(docs)==len(ledger['document_rows'])==len(document_sources)==96
        and set(docs)=={r['candidate_id'] for r in document_sources},'complete96 fresh document annotation/source slots required')
    require(len(families)==len(set(families))==4,'four rendering families required')
    groups=defaultdict(list)
    for source in sources:
        a=singles[source['id']];actual=hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(a['source_sha256']==actual and source.get('source_sha256',actual)==actual,'single annotation source hash differs')
        require(type(a['case_group']) is str and a['case_group'],'single case group missing')
        groups[a['case_group']].append(a['family'])
    require(len(groups)==36 and all(Counter(v)==Counter(families) for v in groups.values()),'36complete four-variant case groups required')
    doc_groups=set();support=Counter()
    for source in document_sources:
        a=docs[source['candidate_id']];actual=hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(a['panel']=='document' and a['source_sha256']==source['source_sha256']==actual,'document annotation source/panel differs')
        require(type(a['supported']) is bool and a['case_group'] and a['case_group'] not in doc_groups,'distinct document cases and explicit support required')
        require(a['family'] in families,'document family differs')
        doc_groups.add(a['case_group']);support[a['supported']]+=1
    require(support=={True:72,False:24} and not set(groups)&doc_groups,'72supported/24guard documents with separate cases required')
    return singles,docs


def reference_rows(records,membership,seed,*,document=False):
    require(seed in SEEDS,'one of three fixed seeds required')
    index={r['id']:r for r in records}
    require(len(index)==len(records)==len(membership) and set(index)==set(membership),'complete unique reference-score inventory required')
    rows=[]
    for identity in sorted(index):
        record,a=index[identity],membership[identity]
        key='joint_exact' if document else 'exact'
        require(type(record.get(key)) is bool,'Boolean full-reference exactness required')
        if document:
            require(record.get('supported') is a['supported'],'scored document support differs from ledger')
            if not a['supported']:continue
        rows.append({'id':identity,'seed':seed,'case_group':a['case_group'],'family':a['family'],'exact':record[key]})
    return rows


def totals(rows,*,single=False):
    require(bool(rows),'nonempty scored slots required')
    require(all(type(r['exact']) is bool for r in rows),'Boolean exactness required')
    result={'count':len(rows),'exact':sum(r['exact'] for r in rows),'exact_rate':sum(r['exact'] for r in rows)/len(rows),
        'independent_authored_case_groups':len({r['case_group'] for r in rows}),
        'fixed_seed_count':len({r['seed'] for r in rows}),
        'family_totals':{f:{'count':sum(r['family']==f for r in rows),'exact':sum(r['family']==f and r['exact'] for r in rows)} for f in sorted({r['family'] for r in rows})}}
    if single:
        grouped=defaultdict(list)
        for r in rows:grouped[r['seed'],r['case_group']].append(r)
        require(all(len(v)==4 and len({r['family'] for r in v})==4 for v in grouped.values()),'four variants per fixed-seed case required')
        counts=Counter(sum(r['exact'] for r in v) for v in grouped.values())
        result['four_variant_case_seed_slots']=len(grouped)
        result['number_of_exact_variants_histogram']={str(i):counts[i] for i in range(5)}
        result['all_four_variants_exact']=counts[4]
        result['all_four_measurement_scope']='Case/seed slots reuse the same authored cases; these are not independent observations.'
    return result


def compare(left,right,*,expected_cases,slots_per_case):
    require({r['seed'] for r in left}==set(SEEDS)=={r['seed'] for r in right},'all three fixed seeds required')
    require(all(type(r['exact']) is bool for r in left+right),'Boolean exactness required')
    result=bootstrap.paired_clusters(left,right,replicates=2000,random_seed=6831)
    require(result['case_groups']==expected_cases and result['slots_per_case_group']==slots_per_case,'declared complete case-cluster denominator differs')
    result.update(left_exact=sum(r['exact'] for r in left),right_exact=sum(r['exact'] for r in right),
        ties=result['both_correct']+result['both_wrong'],delta_correct=result['left_only_correct']-result['right_only_correct'])
    per_seed={}
    for seed in SEEDS:
        a={r['id']:r for r in left if r['seed']==seed};b={r['id']:r for r in right if r['seed']==seed}
        require(set(a)==set(b),'same-seed comparison source identities differ')
        l=sum(r['exact'] for r in a.values());r=sum(x['exact'] for x in b.values())
        wins=sum(a[i]['exact'] and not b[i]['exact'] for i in a);losses=sum(b[i]['exact'] and not a[i]['exact'] for i in a)
        per_seed[str(seed)]={'count':len(a),'left_exact':l,'right_exact':r,'delta_correct':l-r,
            'left_only_correct':wins,'right_only_correct':losses,'ties':len(a)-wins-losses,
            'exact_rate_difference':(l-r)/len(a)}
    result['seed_specific']=per_seed
    result['bootstrap_resamples_seeds']=False
    return result


def verify_inventory(frozen,summary,details):
    models={m['name']:m for m in frozen['models']};pipelines={p['name']:p for p in frozen['pipelines']}
    expected={f'{o}_{a}-{s}' for o in POLICIES for a in ARCHITECTURES for s in SEEDS}
    expected_docs={m+'__'+b for m in expected for b in BOUNDARIES}
    require(len(models)==len(frozen['models'])==18 and set(models)==expected==set(details['single']),'complete18 clause model slots required')
    require(len(pipelines)==len(frozen['pipelines'])==36 and set(pipelines)==expected_docs==set(details['document']),'complete36 fixed-boundary pipelines required')
    for name,m in models.items():
        require(name==f"{m['objective']}_{m['architecture']}-{m['seed']}",'model policy/architecture/seed binding differs')
    for name,p in pipelines.items():
        m=models[p['source_model_name']]
        require(name==m['name']+'__'+p['boundary_policy'] and p['boundary_policy'] in BOUNDARIES
            and all(p[k]==m[k] for k in ('architecture','objective','seed','checkpoint','selected_steps','selection')),'fixed-boundary pipeline/model binding differs')
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            for boundary in BOUNDARIES:
                selected=[pipelines[f'{o}_{architecture}-{seed}__{boundary}'] for o in POLICIES]
                require(all(p['boundary_checkpoint']==selected[0]['boundary_checkpoint'] for p in selected),
                    'paired objectives must retain the identical boundary checkpoint')
    require({m['name'] for m in summary['models']}==expected and {p['name'] for p in summary['pipelines']}==expected_docs,'qualification inventory differs')
    return models,pipelines


def analyze(run_directory,qualification_directory,output):
    output=Path(output).resolve();require(not output.exists(),'analysis output already exists')
    inputs=qualified_inputs(run_directory,qualification_directory)
    frozen,summary,details=inputs['frozen'],inputs['summary'],inputs['details']
    models,pipelines=verify_inventory(frozen,summary,details)
    single_membership,document_membership=memberships(inputs['ledger'],inputs['sources'],inputs['document_sources'],inputs['manifest']['fresh_families'])
    single_rows,document_rows=defaultdict(list),defaultdict(list);per_model,per_pipeline={},{}
    for name,m in models.items():
        scored=details['single'][name]['fresh'];rows=reference_rows(scored['rows'],single_membership,m['seed'])
        require(scored['count']==len(rows)==144 and scored['exact']==sum(r['exact'] for r in rows),'qualifier single exact total differs')
        key=(m['objective'],m['architecture']);single_rows[key].extend(rows)
        per_model[name]={'objective':m['objective'],'architecture':m['architecture'],'seed':m['seed'],
            'selection':m['selection'],'selected_steps':m['selected_steps'],'checkpoint':m['checkpoint'],'metrics':totals(rows,single=True)}
    for name,p in pipelines.items():
        scored=details['document'][name]['fresh_documents'];rows=reference_rows(scored['rows'],document_membership,p['seed'],document=True)
        metric=scored['metrics'];require(len(rows)==metric['supported']==72 and metric['count']==96 and metric['unsupported']==24
            and metric['exact']==sum(r['exact'] for r in rows),'qualifier supported-document exact total differs')
        key=(p['objective'],p['architecture'],p['boundary_policy']);document_rows[key].extend(rows)
        per_pipeline[name]={'objective':p['objective'],'architecture':p['architecture'],'seed':p['seed'],
            'boundary_policy':p['boundary_policy'],'boundary_checkpoint':p['boundary_checkpoint'],
            'selection':p['selection'],'selected_steps':p['selected_steps'],'metrics':totals(rows),
            'guard_count':24,'guard_composed_false_acceptances':metric['unsupported_accepted'],
            'all_source_count':96,'guard_scope':'Guards remain in full qualifier metrics; paired fidelity comparison uses all72 supported documents, including abstentions.'}
    comparisons=[]
    for architecture in ARCHITECTURES:
        for left,right in COMPARISONS:
            comparisons.append({'panel':'fresh_single','architecture':architecture,'left_policy':left,'right_policy':right,
                **compare(single_rows[left,architecture],single_rows[right,architecture],expected_cases=36,slots_per_case=12)})
            for boundary in BOUNDARIES:
                comparisons.append({'panel':'fresh_supported_document','architecture':architecture,'boundary_policy':boundary,
                    'left_policy':left,'right_policy':right,
                    **compare(document_rows[left,architecture,boundary],document_rows[right,architecture,boundary],expected_cases=72,slots_per_case=3)})
    for comparison in comparisons:
        comparison['selected_additional_steps_by_seed']={str(seed):{
            'left':models[f"{comparison['left_policy']}_{comparison['architecture']}-{seed}"]['selected_steps'],
            'right':models[f"{comparison['right_policy']}_{comparison['architecture']}-{seed}"]['selected_steps']}
            for seed in SEEDS}
    result={'schema':SCHEMA,'analyzer':ref(__file__),'bootstrap_helper':ref(bootstrap.__file__),
        'qualification':inputs['summary_ref'],'generation_freeze':inputs['frozen_ref'],'build_freeze':inputs['build_ref'],
        'scored_details':summary['details'],'annotation_ledger':inputs['ledger_ref'],'models':per_model,'pipelines':per_pipeline,
        'single_totals':{o+'_'+a:totals(rows,single=True) for (o,a),rows in single_rows.items()},
        'document_totals':{o+'_'+a+'__'+b:totals(rows) for (o,a,b),rows in document_rows.items()},
        'paired_case_group_comparisons':comparisons,'comparison_count':18,
        'bootstrap':{'replicates':2000,'seed':6831,'sampling_unit':'Authored case, retaining all variants and three fixed seeds together.',
            'single_independent_cases':36,'document_supported_independent_cases':72,'single_slots_per_case':12,'document_slots_per_case':3},
        'correctness_source':'Qualified exact canonical reference matches; documents additionally require exact source occurrence intervals. Abstentions are incorrect on supported cases. Build outcomes are never correctness labels.',
        'training_performed':False,'inference_executed':False,'outputs_or_selections_changed':False,'qualified':False,
        'limitations':['Conditional descriptive intervals over this authored case panel, not uncertainty over seeds, templates or statutes.',
            'The same three seed checkpoints and source cases recur across comparisons. Seeds are fixed, not independently resampled.',
            'This compares complete predeclared training-and-selection policies, including explicit parent fallbacks.',
            'Candidate trials train800 additional updates but selection may retain400 or800. CE versus consistency is not a fixed800-step objective-only effect; selected steps are reported for every paired seed.',
            'Document contrasts hold boundary policy and same-seed boundary checkpoint fixed.',
            'Eighteen overall contrasts plus family totals are exploratory diagnostics; no multiplicity-adjusted or population-wide claim.',
            'All-four-variant fidelity counts case/seed slots; lexical variants and neighboring semantic cases are correlated.']}
    # Producer and qualification artifacts remain the same throughout analysis.
    require(ref(__file__)==result['analyzer'] and ref(bootstrap.__file__)==result['bootstrap_helper'],'analysis producer changed')
    for r in (inputs['summary_ref'],inputs['frozen_ref'],inputs['build_ref'],summary['details'],inputs['ledger_ref']):read_ref(r)
    with output.open('xb') as stream:stream.write((json.dumps(result,indent=2,sort_keys=True)+'\n').encode())
    return ref(output)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-directory',required=True);p.add_argument('--qualification-directory',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(analyze(a.run_directory,a.qualification_directory,a.output),sort_keys=True))

if __name__=='__main__':main()
