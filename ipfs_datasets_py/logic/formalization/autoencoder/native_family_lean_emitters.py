"""Bounded, fail-closed Lean interpretations of actual native projection ASTs.

These are declarations under explicit interpretations, not proofs of source
meaning. Boolean/quantifier structure and discrete LTL have defined Lean
semantics; predicates and deontic/cognitive interpretations are parameters.
Unsupported annotations or opaque surface formulas never become atomic stand-ins.
"""
from __future__ import annotations
import json


class UnsupportedNativeLean(ValueError): pass


def require(value,message):
    if not value: raise UnsupportedNativeLean(message)


def string(value):
    require(type(value) is str and len(value)<=16384 and not any(
        ord(c)<32 and c not in '\n\t\r' or 0xD800<=ord(c)<=0xDFFF for c in value),'bounded_printable_symbol_required')
    return json.dumps(value,ensure_ascii=False)


PRELUDE='''set_option autoImplicit false
structure Interpretation (Entity Agent : Type) where
  agent : String → Agent
  cognitive : String → Agent → (Nat → Prop) → Nat → Prop
  constant : String → Entity
  function : String → List Entity → Entity
  atom : String → List Entity → Nat → Prop
  modal : String → List Entity → Option String → (Nat → Prop) → Nat → Prop
  frame : Entity → String → Entity → Prop
  frameScalar : Entity → String → Entity
  member : Entity → Entity → Prop
  subclass : Entity → Entity → Prop

def nextTime (p : Nat → Prop) (t : Nat) : Prop := p (t + 1)
def alwaysTime (p : Nat → Prop) (t : Nat) : Prop := ∀ u, t ≤ u → p u
def eventuallyTime (p : Nat → Prop) (t : Nat) : Prop := ∃ u, t ≤ u ∧ p u
def untilTime (p q : Nat → Prop) (t : Nat) : Prop :=
  ∃ u, t ≤ u ∧ q u ∧ ∀ v, t ≤ v → v < u → p v
def sinceTime (p q : Nat → Prop) (t : Nat) : Prop :=
  ∃ u, u ≤ t ∧ q u ∧ ∀ v, u < v → v ≤ t → p v
def weakUntilTime (p q : Nat → Prop) (t : Nat) : Prop := untilTime p q t ∨ alwaysTime p t
def releaseTime (p q : Nat → Prop) (t : Nat) : Prop := ¬ untilTime (fun u => ¬ p u) (fun u => ¬ q u) t
'''


class FormulaRenderer:
    def __init__(self): self.nodes=0; self.signatures={}; self.counter=0; self.operators=[]
    def step(self,depth):
        self.nodes+=1
        require(self.nodes<=4096 and depth<=64,'bounded_native_AST_required')
    def signature(self,name,arity):
        require(name not in self.signatures or self.signatures[name]==arity,'inconsistent_native_symbol_arity')
        self.signatures[name]=arity
    def term(self,node,environment,depth=0):
        self.step(depth);require(type(node) is dict,'typed_native_term_required')
        kind=node.get('node_type')
        if kind=='VariableTerm': return self.term(node['variable'],environment,depth+1)
        sort=node.get('sort')
        if isinstance(sort,dict): sort=sort.get('value',sort.get('name'))
        require(sort in (None,'Object'),'multisorted_term_requires_dedicated_Lean_carriers')
        if kind=='Variable':
            require(node['name'] in environment,'free_native_variable_requires_explicit_binding')
            return environment[node['name']]
        if kind=='Constant': return '(i.constant '+string(node['name'])+')'
        if kind in ('FunctionTerm','FunctionApplication'):
            if kind=='FunctionTerm':
                function=node['function'];name=function['name']
                require(function['return_sort']['name']=='Object' and not function['return_sort'].get('parent'),
                        'non_Object_native_function_sort')
                require(len(function['argument_sorts'])==len(node['arguments']) and all(
                    x['name']=='Object' and not x.get('parent') for x in function['argument_sorts']), 'native_function_signature_changed')
            else: name=node['function_name']
            self.signature('function:'+name,len(node['arguments']))
            terms=[self.term(x,environment,depth+1) for x in node['arguments']]
            return '(i.function '+string(name)+' ['+', '.join(terms)+'])'
        raise UnsupportedNativeLean('unsupported_native_term:'+str(kind))
    def formula(self,node,environment=None,depth=0):
        self.step(depth);require(type(node) is dict,'typed_native_formula_required')
        environment={} if environment is None else environment
        kind=node.get('node_type');self.operators.append(kind)
        if kind in ('Predicate','AtomicFormula'):
            predicate=node.get('predicate')
            name=predicate['name'] if predicate is not None else node['name']
            if predicate is not None:
                require(len(predicate['argument_sorts'])==len(node['arguments']) and all(
                    x['name']=='Object' and not x.get('parent') for x in predicate['argument_sorts']), 'native_predicate_sort_not_supported')
            self.signature('predicate:'+name,len(node['arguments']))
            args=[self.term(x,environment,depth+1) for x in node['arguments']]
            return '(fun t => i.atom '+string(name)+' ['+', '.join(args)+'] t)'
        if kind in ('DeonticFormula','CognitiveFormula'):
            op=node['operator']['value'];self.operators.append(op)
            if kind=='CognitiveFormula':
                agent=node.get('agent')
                require(agent and agent['node_type']=='FunctionTerm' and not agent['arguments'] and
                        agent['function']['return_sort']['name']=='agent' and not agent['function']['argument_sorts'],
                        'ground_native_agent_constant_required')
                body=self.formula(node['formula'],environment,depth+1)
                return '(i.cognitive '+string(op)+' (i.agent '+string(agent['function']['name'])+') '+body+')'
            agents=[] if node.get('agent') is None else [self.term(node['agent'],environment,depth+1)]
            require(kind!='CognitiveFormula' or agents,'cognitive_operator_requires_agent')
            context='none' if node.get('context') is None else '(some '+string(node['context'])+')'
            prefix='deontic:' if kind=='DeonticFormula' else 'cognitive:'
            return '(i.modal '+string(prefix+op)+' ['+', '.join(agents)+'] '+context+' '+self.formula(node['formula'],environment,depth+1)+')'
        if kind in ('UnaryFormula','BinaryFormula','ConnectiveFormula'):
            op=node.get('operator',node.get('connective'))['value'];self.operators.append(op)
            children=node.get('formulas') or node.get('operands')
            if children is None: children=[node['formula']] if kind=='UnaryFormula' else [node['left'],node['right']]
            values=[self.formula(x,environment,depth+1)+' t' for x in children]
            if op in ('¬','not'):
                require(len(values)==1,'negation_arity'); body='¬ ('+values[0]+')'
            else:
                symbol={'∧':'∧','and':'∧','∨':'∨','or':'∨','→':'→','implies':'→','↔':'↔','iff':'↔'}.get(op)
                require(symbol is not None and len(values)>=2 and (symbol in ('∧','∨') or len(values)==2),'unsupported_connective_or_arity')
                body=(' '+symbol+' ').join('('+x+')' for x in values)
            return '(fun t => '+body+')'
        if kind=='QuantifiedFormula':
            q=node['quantifier'];q=q.get('value') if isinstance(q,dict) else q
            require(q in ('∀','∃'),'unsupported_quantifier')
            variable=node['variable']; require(variable.get('sort') in (None,{'enum':'Sort','value':'Object'}),'quantified_sort_requires_carrier')
            name='v'+str(self.counter);self.counter+=1
            body=self.formula(node['formula'],{**environment,variable['name']:name},depth+1)
            return '(fun t => '+q+' '+name+' : Entity, '+body+' t)'
        if kind in ('TemporalFormula','BinaryTemporalFormula'):
            require(node.get('time_bound') is None and node.get('time') is None,'explicit_native_time_annotation_not_lowered')
            op=node['operator']['value'];self.operators.append(op)
            names={'□':'alwaysTime','G':'alwaysTime','◊':'eventuallyTime','F':'eventuallyTime','X':'nextTime',
                   'U':'untilTime','S':'sinceTime','W':'weakUntilTime','R':'releaseTime'}
            require(op in names,'unsupported_temporal_operator')
            children=[node['formula']] if kind=='TemporalFormula' else [node['left'],node['right']]
            require(len(children)==(1 if op in ('□','G','◊','F','X') else 2),'temporal_operator_arity')
            return '('+names[op]+' '+' '.join(self.formula(x,environment,depth+1) for x in children)+')'
        raise UnsupportedNativeLean('unsupported_native_formula:'+str(kind))


def native_modal(payload,family):
    """Reparse the original concrete formula and compare the full native AST."""
    from ...autoformal import family_qualification as q
    from ...intent_ir.formalize.modal_projections import _ast
    from ...CEC.native.dcec_integration import parse_dcec_string
    values=payload.get('payload',{}).get('formulas') if payload.get('format') in ('native_tdfol_ast','native_dcec_ast') else None
    if values is None: values=[payload] if 'ast' in payload else []
    require(values,'native_formula_AST_required')
    declarations=[];operators=[]
    for index,row in enumerate(values):
        source=row['source']
        validated=q.validate_family_artifact('dcec' if family=='dcec' else 'tdfol',source)
        require(validated['passed'],'strict_native_formula_reparse_failed')
        parsed=parse_dcec_string(source) if family=='dcec' else q._strict_tdfol(source)[0]
        require(_ast(parsed)==row['ast'],'reparsed_native_AST_differs')
        renderer=FormulaRenderer();expression=renderer.formula(row['ast'])
        declarations.append(f'def formula_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := {expression}')
        operators.extend(renderer.operators)
    return '\n'.join(declarations),{'validator':'strict_native_reparse_and_exact_AST','operators':operators,
        'assumptions':['Object carrier and atomic predicates are arbitrary interpretation parameters.',
            'Deontic/cognitive operators are distinct interpretation parameters; no modal axioms or source truth are asserted.',
            'Supported temporal operators use discrete unbounded Nat traces.']}


def temporal_document(payload):
    from ...software_verification.temporal import TemporalFormula
    native=TemporalFormula.from_dict(payload)
    require(native.to_dict()==payload,'native_temporal_roundtrip_differs')
    operators=[]
    def expression(node,depth=0):
        require(depth<=64 and node['logic']=='ltl' and node['interval'] is None and node['path_quantifier'] is None,
                'only_unbounded_linear_discrete_temporal_fragment_supported')
        op=node['operator'];operators.append(op);children=node['operands']
        if op=='atom':
            require(not children and node['proposition'],'temporal_atom_shape')
            return '(fun t => i.atom '+string(node['proposition'])+' [] t)'
        values=[expression(x,depth+1) for x in children]
        names={'always':('alwaysTime',1),'eventually':('eventuallyTime',1),'next':('nextTime',1),
               'until':('untilTime',2),'weak_until':('weakUntilTime',2),'release':('releaseTime',2)}
        if op in names:
            name,arity=names[op];require(len(values)==arity,'temporal_arity')
            return '('+name+' '+' '.join(values)+')'
        if op=='not':
            require(len(values)==1,'temporal_negation_arity');return '(fun t => ¬ ('+values[0]+' t))'
        require(op in ('and','or','implies','iff') and len(values)==2,'unsupported_typed_temporal_operator')
        return '(fun t => ('+values[0]+' t) '+{'and':'∧','or':'∨','implies':'→','iff':'↔'}[op]+' ('+values[1]+' t))'
    return 'def formula {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := '+expression(payload),{
        'validator':'TemporalFormula.from_dict_exact_roundtrip','operators':operators,
        'assumptions':['Atomic proposition interpretation is supplied by the caller; Nat denotes discrete time, not wall time.']}


def state_document(payload):
    from ...software_verification.transitions import StateTransitionIR
    native=StateTransitionIR.from_dict(payload);require(native.to_dict()==payload,'native_state_roundtrip_differs')
    require(not any(payload.get(k) for k in ('fairness','variants','valuations','kripke','labels')),'state_extra_semantics_require_dedicated_lowering')
    variables=payload['schema']['variables'];require(variables and len(variables)<=64,'bounded_nonempty_state_schema_required')
    fields={};aliases={};bounds=[];lines=['structure State where']
    for index,v in enumerate(variables):
        kind=v['type_kind'];require(kind in ('integer','boolean','enumeration'),'state_type_not_lowered')
        field='v'+str(index);fields[v['variable_id']]=(field,kind)
        for key in (v['variable_id'],v['name']):
            require(key not in aliases or aliases[key]==v['variable_id'],'ambiguous_state_variable_alias');aliases[key]=v['variable_id']
        lines.append('  '+field+' : '+{'integer':'Int','boolean':'Bool','enumeration':'String'}[kind])
        bound=v.get('domain_bound');require(v['boundedness']=='finite' and bound is not None,'finite_state_bound_required')
        require(bound['cardinality'] is None or kind=='boolean' and bound['cardinality']==2, 'finite_cardinality_requires_explicit_lowering')
        if kind=='boolean':
            require(bound['cardinality']==2 and bound['lower'] is None and bound['upper'] is None and not bound['members'], 'only_intrinsic_two_value_Bool_bound_supported')
        if kind=='enumeration':
            require(bound['members'] and bound['lower'] is None and bound['upper'] is None,'explicit_enum_bound_required')
            bounds.append('s.'+field+' ∈ ['+', '.join(string(x) for x in bound['members'])+']')
        elif kind=='integer':
            require(type(bound['lower']) is int and type(bound['upper']) is int and not bound['members'],'integer_interval_required')
            bounds.append(f'({bound["lower"]} : Int) ≤ s.{field} ∧ s.{field} ≤ ({bound["upper"]} : Int)')
    lines += ['def typeOK (s : State) : Prop := '+(' ∧ '.join('('+x+')' for x in bounds) or 'True')]
    predicates={};roles={};dependencies={}
    for index,p in enumerate(payload['predicates']):
        require(p['role'] in ('initial','guard','next','invariant'),'unsupported_state_predicate_role')
        values=p['expression'];require(type(values) is dict and values,'structured_state_equality_map_required')
        clauses=[]
        for key,value in values.items():
            require(key in aliases,'state_expression_unknown_variable')
            field,kind=fields[aliases[key]]
            require((kind=='integer' and type(value) is int) or (kind=='boolean' and type(value) is bool) or
                    (kind=='enumeration' and type(value) is str),'typed_state_literal_required')
            rendered=string(value) if kind=='enumeration' else str(value).lower() if kind=='boolean' else '('+str(value)+' : Int)'
            clauses.append('s.'+field+' = '+rendered)
        name='predicate_'+str(index);predicates[p['predicate_id']]=name;roles[p['predicate_id']]=p['role']
        dependencies[p['predicate_id']]={aliases[key] for key in values}
        lines.append('def '+name+' (s : State) : Prop := '+' ∧ '.join('('+x+')' for x in clauses))
    initial=[name+' s' for key,name in predicates.items() if roles[key]=='initial']
    require(initial,'explicit_initial_state_required')
    lines.append('def initial (s : State) : Prop := typeOK s ∧ ('+' ∧ '.join(initial)+')')
    invariants=[name+' s' for key,name in predicates.items() if roles[key]=='invariant']
    lines.append('def invariants (s : State) : Prop := '+(' ∧ '.join(invariants) or 'True'))
    actions={}
    for index,action in enumerate(payload['actions']):
        require(not action['label_ids'] and not action['enables_stutter'],'action_labels_or_local_stutter_not_lowered')
        frame=action['frame'];require(not frame['allows_all_writes'],'unbounded_write_frame_not_lowered')
        require(set(frame['writes'])<=set(fields),'unknown_write_frame')
        guard=action['guard_predicate_id'];nxt=action['next_predicate_id']
        require(nxt in predicates and roles[nxt]=='next' and (not guard or guard in predicates and roles[guard]=='guard'),'action_predicate_role_mismatch')
        reads=set(frame['reads']);require(reads<=set(fields),'unknown_read_frame')
        guard_reads=dependencies.get(guard,set())
        require(frame['allows_all_reads'] or guard_reads<=reads,'guard_reads_outside_declared_action_frame')
        frame_name='readFrame_'+str(index)
        lines.append('def '+frame_name+' (variableName : String) : Bool := '+('true' if frame['allows_all_reads'] else '['+', '.join(string(x) for x in sorted(reads))+'].contains variableName'))
        lines.append('example : ['+', '.join(string(x) for x in sorted(guard_reads))+'].all '+frame_name+' = true := by decide')
        clauses=[predicates[guard]+' s'] if guard else []
        clauses += [predicates[nxt]+' t']
        clauses += ['t.'+field+' = s.'+field for key,(field,_) in fields.items() if key not in frame['writes']]
        name='action_'+str(index);actions[action['action_id']]=name
        lines.append('def '+name+' (s t : State) : Prop := '+' ∧ '.join('('+x+')' for x in clauses))
    relations=[]
    for index,relation in enumerate(payload['transitions']):
        require(relation['kind']=='action' and not relation['predicate_id'] and relation['action_ids'],'unsupported_state_relation')
        require(set(relation['action_ids'])<=set(actions),'unknown_transition_action')
        choices=['label = '+string(key)+' ∧ '+actions[key]+' s t' for key in relation['action_ids']]
        if relation['allows_stutter']: choices.append('label = "stutter" ∧ t = s')
        name='transition_'+str(index);relations.append(name+' label s t')
        lines.append('def '+name+' (label : String) (s t : State) : Prop := '+' ∨ '.join('('+x+')' for x in choices))
    require(relations,'explicit_state_transition_required')
    lines.append('def next (label : String) (s t : State) : Prop := typeOK s ∧ typeOK t ∧ ('+' ∨ '.join(relations)+')')
    return '\n'.join(lines),{'validator':'StateTransitionIR.from_dict_exact_roundtrip','operators':['typed_state_equality','initial','guard','next','write_frame','labelled_transition'],
        'assumptions':['Only finite typed state equality-map predicates and labelled actions are lowered.',
            'Native declarations describe allowed transitions, not observed execution or verified source behavior.']}


def supplied_formula(payload):
    """Lower a replayed source-bound native formula, never reconstruct from text slots."""
    from ...intent_ir.formalize.modal_projections import _ast
    kind=payload['ast_format'];source=payload['formula'];ast=payload['native_ast']
    if kind in ('tdfol_native','dcec_native'):
        if kind=='tdfol_native':
            from ...autoformal.family_qualification import _strict_tdfol
            parsed=_strict_tdfol(source)[0]
        else:
            from ...CEC.native.dcec_integration import parse_dcec_string
            parsed=parse_dcec_string(source)
        require(_ast(parsed)==ast,'source_bound_native_formula_AST_reparse_differs')
        renderer=FormulaRenderer();body=renderer.formula(ast)
        return 'def formula {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := '+body,{
            'validator':'replayed_native_formula_evidence_and_exact_AST_reparse','operators':renderer.operators,
            'assumptions':['Atomic predicates and distinct deontic/cognitive operators are interpretation parameters.',
                'Native Object and agent sorts have separate arbitrary Lean carrier types.',
                'Temporal operators use discrete unbounded Nat traces; no modal axioms or event-calculus axioms asserted.']}
    if kind=='shared_logic':
        from ...parsers.modal import parse_modal, profile_k
        parsed=parse_modal(payload['printed'], profile_k())
        require(parsed.ok and not parsed.diagnostics and parsed.root.to_dict()==ast,'shared_propositional_reparse_differs')
        operators=[]
        def boolean(node,depth=0):
            require(depth<=64 and not node.get('binders') and not node.get('extension'),'propositional_core_only')
            op=node['kind'];operators.append(op);args=node['arguments']
            if op=='predicate':
                require(not args,'nullary_proposition_required')
                return '(i.atom '+string(node['symbol'])+' [] t)'
            if op in ('true','false'): return op.title()
            if op=='not':
                require(len(args)==1,'propositional_not_arity');return '(¬ '+boolean(args[0],depth+1)+')'
            require(op in ('and','or','implies','iff') and len(args)>=2 and (op in ('and','or') or len(args)==2),'unsupported_propositional_operator')
            return '('+(' '+{'and':'∧','or':'∨','implies':'→','iff':'↔'}[op]+' ').join(boolean(x,depth+1) for x in args)+')'
        body=boolean(ast)
        return 'def formula {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) : Prop := '+body,{
            'validator':'strict_shared_propositional_AST_reparse','operators':operators,
            'assumptions':['Nullary proposition truth is supplied by the interpretation.']}
    if kind=='flogic_native':
        from ...parsers.flogic import parse_flogic
        parsed=parse_flogic(payload['printed'])
        require(parsed.ok and not parsed.diagnostics and parsed.document.to_dict()==ast,'native_FLogic_reparse_differs')
        operators=[];definitions=[]
        def ground(term):
            require(term['kind'] in ('constant','string') and not term['arguments'],'ground_FLogic_term_required')
            return '(i.constant '+string(json.dumps({'kind':term['kind'],'name':term['name']},sort_keys=True,separators=(',',':')))+')'
        for index,statement in enumerate(ast['statements']):
            require(statement['kind']=='fact' and not statement['body'] and not statement['unsupported_reason'],'FLogic_rule_lowering_required')
            head=statement['head'];subject=ground(head['object']);clauses=[]
            if head['isa'] is not None: clauses.append('i.member '+subject+' '+ground(head['isa']));operators.append('membership')
            if head['subclass_of'] is not None: clauses.append('i.subclass '+subject+' '+ground(head['subclass_of']));operators.append('subclass')
            for spec in head['specs']:
                require(spec['method']['kind']=='constant' and not spec['method']['arguments'],'ground_FLogic_method_required')
                method=string(spec['method']['name']);values=spec['values'];op=spec['kind'];operators.append(op)
                if op=='scalar_value':
                    require(len(values)==1,'scalar_FLogic_arity');clauses.append('i.frameScalar '+subject+' '+method+' = '+ground(values[0]))
                else:
                    require(op=='set_value' and values,'unsupported_FLogic_slot_operator')
                    clauses.extend('i.frame '+subject+' '+method+' '+ground(value) for value in values)
            require(clauses,'empty_FLogic_fact')
            definitions.append(f'def frame_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Prop := '+' ∧ '.join('('+x+')' for x in clauses))
        return '\n'.join(definitions),{'validator':'strict_native_FLogic_AST_reparse','operators':operators,
            'assumptions':['Scalar methods are interpreted functions; multivalued slots and class relations are interpreted predicates.']}
    raise UnsupportedNativeLean('unsupported_source_bound_AST_format:'+str(kind))

def canonical_norms(payload):
    from ...legal_ir.canonical_contracts import CanonicalRoundTripIR
    native=CanonicalRoundTripIR.from_dict(payload)
    require(native.to_dict()==payload,'canonical_norm_roundtrip_differs')
    require(len(native.rules)<=1024,'bounded_canonical_norms_required')
    lines=[];operators=[]
    for index,rule in enumerate(native.rules):
        require(not (rule.conditions or rule.exceptions or rule.temporal),
                'qualified_canonical_rule_requires_condition_exception_temporal_semantics')
        args=[rule.actor]+([rule.object] if rule.object else [])
        terms=', '.join('(i.constant '+string(value)+')' for value in args)
        body='(fun t => i.atom '+string(rule.action)+' ['+terms+'] t)'
        lines.append(f'def norm_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := i.modal '+string('deontic:'+rule.modality)+' [] none '+body)
        operators.append('deontic:'+rule.modality)
    return '\n'.join(lines),{'validator':'CanonicalRoundTripIR.from_dict_exact_unqualified_rule_roundtrip',
        'operators':operators,'rule_count':len(native.rules),
        'assumptions':['O/P/F are distinct supplied norm interpretations, not asserted axioms.',
            'Actor is the first predicate argument; a nonempty object is the second. Empty object denotes absence.',
            'All conditions, exceptions and temporal qualifiers require a different lowering and are rejected.']}

def emit_projection(row):
    """Return actual Lean definitions or an explicit unsupported exception."""
    payload=row['payload'];family=row['logic_family'];pid=row['projection_id']
    if pid=='legal-ir/canonical-norms/v1' and family=='deontic': return canonical_norms(payload)
    if isinstance(payload,dict) and {'formula','printed','native_ast','ast_format','source_ref','requirement_id','operator_counts'}<=set(payload):
        return supplied_formula(payload)
    if family in ('tdfol','dcec') and isinstance(payload,dict) and (
            'ast' in payload or payload.get('format') in ('native_tdfol_ast','native_dcec_ast')):
        return native_modal(payload,family)
    if family=='higher_order' and isinstance(payload,dict):
        source=payload.get('source') if payload.get('format')=='lean4-source' else payload.get('payload',{}).get('lean_source')
        require(source and ('namespace IntentProjection' in source or 'namespace TypedSlotFixture' in source),'known_native_Lean_generator_required')
        import re
        require(not re.search(r'(?m)^\s*(?:import|axiom|constant|unsafe)\b|\b(?:sorry|admit|sorryAx)\b',source),'unsafe_native_Lean_source')
        return source,{'validator':'exact_native_source_replay_existing_Intent_Lean_generator','operators':['typed_predicate','parameterized_modality'],
            'assumptions':['Native Lean emitter assumptions are retained in its original generated source and source-bound payload.']}
    if family=='temporal' and isinstance(payload,dict) and payload.get('schema_version')=='temporal-formula/v1':
        return temporal_document(payload)
    if family=='transition_system' and isinstance(payload,dict):
        if payload.get('schema_version')=='state-transition-ir/v1': return state_document(payload)
        document=payload.get('native_document') or payload.get('bridge',{}).get('expression',{}).get('root',{}).get('extension',{}).get('payload',{}).get('document')
        if document and 'tla_plus' not in pid: return state_document(document)
        # A TLA artifact adds boundedness/configuration semantics; a state-only
        # Lean model cannot validate those by silently dropping the artifact.
        raise UnsupportedNativeLean('TLA_artifact_semantics_require_additional_Lean_lowering' if 'tla_plus' in pid else 'native_state_document_required')
    if family=='frame_logic':
        triples=[]
        if isinstance(payload,list) and all(set(('subject','predicate','object'))<=set(x) for x in payload): triples=payload
        elif isinstance(payload,dict):
            triples=payload.get('payload',{}).get('frame_logic',{}).get('triples',[])
            if not triples and set(payload)<= {'facts'}:
                for fact in payload['facts']:
                    require(len(fact['args'])==2,'binary_frame_fact_required')
                    triples.append(dict(subject=fact['args'][0],predicate=fact['predicate'],object=fact['args'][1]))
        require(triples,'actual_native_frame_triples_required')
        definitions=[]
        for index,triple in enumerate(triples):
            definitions.append(f'def frame_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Prop := i.frame (i.constant '+string(triple['subject'])+') '+string(triple['predicate'])+' (i.constant '+string(triple['object'])+')')
        return '\n'.join(definitions),{'validator':'exact_native_frame_record_source_replay','operators':['frame_relation'],
            'assumptions':['Frame triples are interpreted relations; declaration records do not establish the source proposition.']}
    raise UnsupportedNativeLean('no_semantics_preserving_Lean_emitter_for_projection:'+pid)
