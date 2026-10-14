"""Author detached source/synthetic evaluator controls; no actual saved bodies."""
import ast,hashlib,json
from pathlib import Path
F=Path(__file__).resolve().parent;P=F.parent/'legal-actor-refinement-20261014-01'
model=F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_context_ranking.py'
mb=model.read_bytes();modelpin=(len(mb),hashlib.sha256(mb).hexdigest())
cb=(F/'evaluation-contract-v01.json').read_bytes();contractpin=(len(cb),hashlib.sha256(cb).hexdigest())
def function(src,name,replacement):
 n=next(n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name==name);lines=src.splitlines(keepends=True)
 return ''.join(lines[:n.lineno-1])+replacement.rstrip()+'\n'+''.join(lines[n.end_lineno:])
def method(src,name,replacement):
 n=next(n for n in ast.walk(ast.parse(src)) if isinstance(n,ast.FunctionDef) and n.name==name);lines=src.splitlines(keepends=True)
 return ''.join(lines[:n.lineno-1])+replacement.rstrip()+'\n'+''.join(lines[n.end_lineno:])
def port(name):
 s=(P/name).read_text().replace('actor-refinement','actor-context-ranking').replace('actor_refinement','actor_context_ranking')
 s=s.replace("STATES=('parent','initial','trained')","STATES=('frozen_N11','parent','initial','trained')")
 s=s.replace('source_conditions_presence','source_actor_refinement')
 s=s.replace('34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd','f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4')
 s=s.replace('b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9','a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42')
 s=s.replace("bytes=56952,sha256='a6b004330c0b0be63182e5931d9d77654ae0a3144526113fc9bd3075a121642e'",f"bytes={modelpin[0]},sha256='{modelpin[1]}'")
 s=s.replace("(12913,'a8e64cee523d57149b6becaf18023bf87a9ecdb147d83e9c42453fce9230944e')",repr(contractpin))
 s=s.replace('actor-context-ranking-ce','actor-context-ranking-hinge')
 return s
a=port('test_actor_refinement_analyzer_detached_v01.py')
a=a.replace("('actor-context-ranking-joint-panel/v1','conditions-presence-joint-panel/v1')",
 "('actor-context-ranking-joint-panel/v1','actor-refinement-joint-panel/v1','conditions-presence-joint-panel/v1')")
a=a.replace("'a6b004330c0b0be63182e5931d9d77654ae0a3144526113fc9bd3075a121642e'",repr(modelpin[1]))
a=a.replace("if __name__=='__main__':unittest.main(verbosity=2)",'''class BothComparatorControls(unittest.TestCase):
    def test_each_comparator_scope_route_loss_veto_is_independent(self):
        for state,key,other in (('frozen_N11','N11','parent'),('parent','F15','frozen_N11')):
            for panel in SCOPES:
                for route in ('raw','joint'):
                    records,p=fixture()
                    records[other,panel][0][route+'_exact_ir']=False
                    records['trained',panel][0][route+'_exact_ir']=False
                    if panel=='training168':records['trained',panel][155][route+'_exact_ir']=True
                    result=NS['scientific_acceptance'](CONTRACT,records,p)
                    self.assertFalse(result['scientific_success'])
                    self.assertEqual(result['no_complete_IR_loss_IDs_vs_'+key]['loss_ids_by_scope'][panel][route],[panel+'0'])
                    otherkey='F15' if key=='N11' else 'N11'
                    self.assertEqual(result['no_complete_IR_loss_IDs_vs_'+otherkey]['loss_ids_by_scope'][panel][route],[])

    def test_all_four_permission_states_and_complete36_scores_required(self):
        for state in NS['STATES']:
            records,p=fixture();p[state]['raw_P_to_P']=31
            self.assertFalse(NS['scientific_acceptance'](CONTRACT,records,p)['scientific_success'])
            records,p=fixture();del records[state,'fresh_test']
            with self.assertRaises(ValueError):NS['scientific_acceptance'](CONTRACT,records,p)

    def test_both_comparator_policies_and_typed_unique_rows_required(self):
        for key in ('N11','F15'):
            c=copy.deepcopy(CONTRACT);c['strict_scientific_success']['no_complete_IR_loss_IDs_vs_'+key]['allowed_loss_count_each_scope_and_view']=1
            with self.assertRaises(ValueError):NS['scientific_acceptance'](c,*fixture())
        for mutate in (lambda r:r['parent','old_tune'][1].update(id=r['parent','old_tune'][0]['id']),
                       lambda r:r['frozen_N11','old_tune'][0].update(raw_exact_ir=1)):
            r,p=fixture();mutate(r)
            with self.assertRaises(ValueError):NS['scientific_acceptance'](CONTRACT,r,p)

if __name__=='__main__':unittest.main(verbosity=2)''')
r=port('test_actor_refinement_recount_detached_v01.py')
r=r.replace("correct=154 if state=='parent' and panel=='training168' else 155 if panel=='training168' else COUNTS[panel]",
 "correct=(155 if state=='trained' else 154) if panel=='training168' else COUNTS[panel]")
r=r.replace("loss=1.25,gradient_norm=1.","loss=1.5,gradient_norm=1.")
r=r.replace('actor_hinge_applied=False','actor_hinge_applied=True').replace('gradient_enabled_by_policy=False','gradient_enabled_by_policy=True')
r=r.replace('total_loss=1.25','total_loss=1.5').replace('batch_losses=[1.25]*32','batch_losses=[1.5]*32')
r=r.replace("initial={name:digest(name) for name in branches};before=dict(initial);frozen=initial['frozen_nonactor36_state_sha256'];inactive=initial['inactive_actor_head_rows_sha256']",
 "initial={name:digest(name) for name in branches};initial['frozen_nonactor36_state_sha256']='6d367a28a38e7244fddcd60ec0db137f3c534c0363fb993fe7b28678d2261507';before=dict(initial);frozen=initial['frozen_nonactor36_state_sha256'];inactive=initial['inactive_actor_head_rows_sha256']")
r=r.replace("rows.append(dict(id=source['id'],training_index=index,token_count=3,actor_gold_coordinates=[0,0],actor_present=True))",
 "rows.append(dict(id=source['id'],training_index=index,token_count=3,actor_gold_coordinates=[0,0],actor_present=True,source_sha256=sha,\n                present_gold_nonactor_coordinates=dict(action=[1,1]),compatible_wrong_candidate_count=1,compatible_wrong_domain_sha256=digest([(2,2)])))")
r=method(r,'test_actual_sourceSHA_authentication_exceeds_owner_validator',"""    def test_actual_sourceSHA_authentication_exceeds_owner_validator(self):
        report,training,schedule=training_fixture(self.ns)
        objective=report['objective_trace']['batches'][4]
        objective['details']['base_objective']['rows'][0]['source_sha256']='f'*64
        objective['details']['rows'][0]['source_sha256']='f'*64
        self.ns['load_training_validators']()['trainer']['_validate_objective_entry'](objective,report['batch_trace']['batches'][4],report['training_policy'])
        reseal_traces(self.ns,report)
        with self.assertRaisesRegex(ValueError,'source/gold actor'):self.ns['recount_training'](report,training,schedule)
""")
r=method(r,'test_actual_gold_coordinates_authentication_exceeds_owner_validator',"""    def test_actual_gold_coordinates_authentication_exceeds_owner_validator(self):
        report,training,schedule=training_fixture(self.ns);objective=report['objective_trace']['batches'][4]
        objective['details']['rows'][0].update(actor_gold_coordinates=[2,2],compatible_wrong_domain_sha256=self.ns['digest']([(0,0)]))
        row=objective['details']['base_objective']['rows'][0]
        row.update(gold_coordinates=[2,2],chosen_wrong_coordinates=[0,0],compatible_wrong_domain_sha256=self.ns['digest']([(0,0)]))
        self.ns['load_training_validators']()['trainer']['_validate_objective_entry'](objective,report['batch_trace']['batches'][4],report['training_policy'])
        reseal_traces(self.ns,report)
        with self.assertRaisesRegex(ValueError,'source/gold actor'):self.ns['recount_training'](report,training,schedule)
""")
r=r.replace("if __name__=='__main__':unittest.main()",'''class BothComparatorAndRankingControls(unittest.TestCase):
    def test_each_comparator_nine_scope_both_route_loss_veto(self):
        ns=namespace()
        for state,key,other in (('frozen_N11','N11','parent'),('parent','F15','frozen_N11')):
            for panel in SCOPES:
                for route in ('raw','joint'):
                    c,r,p=fixture();r[other,panel][0][route]['full_IR']=False;r['trained',panel][0][route]['full_IR']=False
                    if panel=='training168':r['trained',panel][155][route]['full_IR']=True
                    out=ns['independent_acceptance'](c,r,p)
                    self.assertFalse(out['scientific_success'])
                    self.assertEqual(out['no_complete_IR_loss_IDs_vs_'+key]['loss_ids_by_scope'][panel][route],[panel+'-0'])
                    self.assertEqual(out['no_complete_IR_loss_IDs_vs_'+('F15' if key=='N11' else 'N11')]['loss_ids_by_scope'][panel][route],[])

    def test_ranking_disabled_and_wrapper_bool_float_index_refused(self):
        ns=namespace()
        report,training,schedule=training_fixture(ns)
        self.assertTrue(report['training_policy']['objective_policy']['actor_ranking_enabled'])
        self.assertEqual(report['training_policy']['objective_policy']['actor_hinge_coefficient'],.25)
        self.assertEqual(report['training_policy']['objective_policy']['actor_hinge_margin'],1.)
        report['training_policy']['objective_policy']['actor_ranking_enabled']=False
        with self.assertRaises(ValueError):ns['recount_training'](report,training,schedule)
        for value in (True,1.0):
            report,training,schedule=training_fixture(ns)
            report['objective_trace']['batches'][0]['details']['rows'][0]['training_index']=value
            reseal_traces(ns,report)
            with self.assertRaises(ValueError):ns['recount_training'](report,training,schedule)

    def test_no_complete_argmax_or_numerical_gradient_claim(self):
        ns=namespace();report,training,schedule=training_fixture(ns);out=ns['recount_training'](report,training,schedule)
        self.assertTrue(out['actor_ranking_enabled'])
        self.assertTrue(out['selected_scalar_hinge_and_filtered_domain_replayed'])
        self.assertFalse(out['independent_complete_preupdate_argmax_replay'])
        self.assertFalse(out['independent_numerical_gradient_proof'])

if __name__=='__main__':unittest.main()''')
for name,body in [('test_actor_context_ranking_analyzer_detached_v01.py',a),('test_actor_context_ranking_recount_detached_v01.py',r)]:
 p=F/name;compile(body,str(p),'exec')
 with p.open('x') as h:h.write(body)
 print(name,len(body.encode()))
