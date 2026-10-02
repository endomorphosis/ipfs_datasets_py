"""Typed AND/OR plans for the reviewed CodebaseIR family execution profile."""
from __future__ import annotations
from itertools import product

from .codebase_family_lowering import CodebaseFamilyBundle, _require
from .content import cid_for_structured
from ..software_verification.tactician.contracts import (
    ProofObligationGraph, ProofGraphNode, ProofGraphEdge, GraphNodeKind, GraphEdgeKind,
)
from ..software_verification.tactician.proof_plan import MissingProofPlanAlternative, ProofPlanStepSpec

SCHEMA = "codebase-family-obligation-plans@1"
KERNELS = ("lean", "rocq", "isabelle")


def build_codebase_obligation_plans(bundles):
    """Pure proposals. Only the separate native executor can supply results."""
    _require(type(bundles) in (tuple,list) and 1 <= len(bundles) <= 2
             and all(type(b) is CodebaseFamilyBundle for b in bundles)
             and len({b.compiled.contract.path for b in bundles}) == len(bundles),
             "one or two distinct exact source-unit family bundles required")
    bundle_ids = [b.cid for b in bundles]
    identity = cid_for_structured(dict(schema=SCHEMA,bundles=bundle_ids))
    nodes=[ProofGraphNode('root',GraphNodeKind.ROOT,obligation_id=identity),
           ProofGraphNode('all',GraphNodeKind.AND,obligation_id=identity),
           ProofGraphNode('current-source',GraphNodeKind.LEAF,obligation_id='current-source:'+identity,
                          metadata=dict(operation='final_live_source_and_policy_revalidation',required=True))]
    edges=[]
    leaves={}
    def edge(a,b,kind=GraphEdgeKind.DEPENDS_ON):
        edges.append(ProofGraphEdge('edge:'+str(len(edges)),a,b,kind,inference_rule='closed_profile_required_obligation'))
    edge('root','all');edge('all','current-source')
    for index,bundle in enumerate(bundles):
        prefix='unit'+str(index);binding=bundle.to_dict()
        unit=prefix+':all';choice=prefix+':kernel'
        nodes.extend((ProofGraphNode(unit,GraphNodeKind.AND,obligation_id=bundle.cid),
            ProofGraphNode(choice,GraphNodeKind.OR,obligation_id=bundle.cid)))
        edge('all',unit);edge(unit,choice)
        for kernel in KERNELS:
            node=prefix+':'+kernel
            metadata=dict(kind='mathematical_portfolio',bundle_cid=bundle.cid,kernel=kernel,
                families=['smt_lia',{'lean':'lean4','rocq':'rocq','isabelle':'isabelle_hol'}[kernel]],
                operation=binding['operation'],assumptions=binding['assumptions'],domain='unbounded_integer',
                source_cid=bundle.compiled.source_cid,contract_cid=bundle.compiled.contract.cid,
                assurance='native_kernel_reconstruction_required')
            nodes.append(ProofGraphNode(node,GraphNodeKind.LEAF,obligation_id=bundle.cid,metadata=metadata));edge(choice,node,GraphEdgeKind.ALTERNATIVE)
            leaves[node]=metadata
        for role in ('finite','bridge'):
            node=prefix+':'+role
            metadata=dict(kind=role,bundle_cid=bundle.cid,operation='finite_invariant' if role=='finite' else 'finite_restriction_bridge',
                families=['tla_plus'] if role=='finite' else ['mathematical_integer','lean4','tla_plus'],
                assumptions=binding['assumptions'],domain=binding['finite_inputs'],source_cid=bundle.compiled.source_cid,
                contract_cid=bundle.compiled.contract.cid,assurance='bounded_model_check' if role=='finite' else 'native_kernel_bridge_required',
                depends_on=[choice] if role=='bridge' else [])
            nodes.append(ProofGraphNode(node,GraphNodeKind.LEAF,obligation_id=bundle.cid+':'+role,metadata=metadata));edge(unit,node)
            leaves[node]=metadata
            if role == "bridge":edge(node,choice)
    graph=ProofObligationGraph(graph_id=identity,formal_goal_id=identity,root_node_id='root',nodes=tuple(nodes),edges=tuple(edges))
    alternatives=[]
    for choices in product(KERNELS,repeat=len(bundles)):
        selected=['current-source']+[name for i,kernel in enumerate(choices) for name in ('unit'+str(i)+':'+kernel,'unit'+str(i)+':finite','unit'+str(i)+':bridge')]
        steps=[]
        for name in selected:
            if name=='current-source':
                dependencies=tuple(n for n in selected if n!='current-source');operation='final source/policy fence'
            else:
                dependencies=tuple(n for n in selected if n.startswith(name.split(':')[0]+':') and n.endswith(choices[int(name.split(':')[0][4:])])) if name.endswith(':bridge') else ()
                operation=leaves[name]['operation']
            steps.append(ProofPlanStepSpec(step_id=name,obligation_id=name+':'+identity,statement=operation,
                dependencies=dependencies,expected_receipts=('exact_source_bound_native_receipt:'+name,),
                validation=('native_replay_and_exact_family_domain_assumption_binding',),
                fallback=('preserve_unavailable_unknown_timeout_or_refuted_frontier',),
                resources=('shared_repository_parent_and_native_child_lease',),
                completion_conditions=('all_required_validations_complete_without_disagreement_or_source_drift',)))
        alternatives.append(MissingProofPlanAlternative(plan_id=identity+':'+str(len(alternatives)),formal_goal_id=identity,
            graph_id=identity,tree_id=identity,steps=tuple(steps),required_obligation_ids=tuple(s.obligation_id for s in steps),
            alternative_ids=tuple(str(i)+':'+choice for i,choice in enumerate(choices)),
            producer_kinds=tuple('codebase_family_native_portfolio:'+str(i)+':'+choice for i,choice in enumerate(choices)),
            metadata=dict(scope='closed_source_model_and_finite_restriction',runtime_proof=False)))
    return dict(schema=SCHEMA,graph=graph.to_dict(),alternatives=[p.to_dict() for p in alternatives],
                leaves=leaves,bundle_ids=bundle_ids,proof_claimed=False,completion_claimed=False)
