"""Replay the fixed authored A/B norms and prepare conditional Lean text.

This is the retained full-norm composition profile, not a statute translator or
a generic theorem prover. Original requests and complete reports are replayed
by the existing relational owner. No backend, model or resource owner is run.
"""
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "legal-full-norm-consequences/v1"
PROFILE = "authored-assign-transfer-approve-ab-conditional/v1"
MAX_REQUEST_BYTES = 524288
MAX_REPORT_BYTES = 8 * 1024 * 1024
THEOREMS = ("LegalFullNorms.CandidateA.norm_instance",
            "LegalFullNorms.CandidateA.approval_from_permission",
            "LegalFullNorms.CandidateB.modal_instance")
ASSUMPTIONS = (
    "Each hNorm is an unverified hypothesis for the whole closed quantified/modal norm at one shared interpretation and fixed Nat time.",
    "A approval additionally requires hPermit for exactly P(Assign(r,d) or Transfer(r,d)) with unchanged argument order and the same interpretation/time.",
    "B yields only its complete permitted implication; no modal elimination, distribution, source truth, governing applicability or norm rewrite is assumed.",
    "Text preparation has not compiled Lean or checked any theorem with a native kernel.",
)
AUTHORITY = dict.fromkeys(("source_truth", "source_equivalence", "legal_acceptance",
    "governing_selection", "review_authorization", "semantic_graph_admission",
    "proof_authority", "training_gold_qualified", "evaluation_gold_qualified"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    remaining = 150000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 96, "bounded ordinary JSON required")
        if type(item) is dict:
            for key, child in item.items():
                _need(type(key) is str, "ordinary string keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need(len(item) <= MAX_REPORT_BYTES and "\x00" not in item,
                  "bounded strings without NUL required")
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded integer required")
        else:
            raise ValueError("ordinary finite JSON required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("ordinary UTF8 JSON required") from error
    _need(len(raw) <= MAX_REPORT_BYTES, "report byte bound exceeded")
    return raw


def _ab(value):
    _need(type(value) is dict and set(value) == {"A", "B"},
          "exact A/B mapping required")


def _unprivileged(value):
    authority = masks = 0
    if type(value) is dict:
        for key, child in value.items():
            if key == "authority":
                _need(type(child) is dict and child and all(flag is False for flag in child.values()),
                      "authority object must remain false")
                authority += 1
            if key.endswith("_mask"):
                _need(type(child) is int and child == 0, "mask must remain integer zero")
                masks += 1
            elif key in {"masks", "field_masks"}:
                _need(type(child) is dict and all(type(flag) is int and flag == 0 for flag in child.values()),
                      "field masks must remain integer zero")
                masks += len(child)
            a, m = _unprivileged(child)
            authority, masks = authority + a, masks + m
    elif type(value) is list:
        for child in value:
            a, m = _unprivileged(child)
            authority, masks = authority + a, masks + m
    return authority, masks


def _owners():
    from . import legal_relational_norm_v1 as owner
    from ..formalization.autoencoder import native_family_lean_emitters as emitter
    return owner, emitter


def prepare_full_norm_consequences_v1(reports, request_raw, *,
        expected_request_sha256, expected_report_sha256):
    """Require independently pinned complete A/B reports and original requests.

    Each argument is a closed ``{"A": ..., "B": ...}`` mapping. Hashes commit
    supplied evidence; they do not authenticate its legal meaning or origin.
    """
    for value in (reports, request_raw, expected_request_sha256, expected_report_sha256):
        _ab(value)
    copied = {}
    for label in ("A", "B"):
        for pins in (expected_request_sha256, expected_report_sha256):
            _need(type(pins[label]) is str and _SHA.fullmatch(pins[label]), "independent lowercase SHA256 required")
        raw = request_raw[label]
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
              "bounded original request bytes required")
        _need(_sha(raw) == expected_request_sha256[label], "request SHA256 mismatch")
        report_raw = _wire(reports[label])
        _need(_sha(report_raw) == expected_report_sha256[label], "report SHA256 mismatch")
        copied[label] = json.loads(report_raw)
        try:
            _actual_shape(copied[label], label)
        except (KeyError, TypeError, IndexError) as error:
            raise ValueError("complete exact authored A/B report shape required") from error
    owner, emitter = _owners()
    replayed = {label: owner.validate_relational_norm_v1(copied[label], request_raw[label],
        expected_request_sha256=expected_request_sha256[label],
        expected_report_sha256=expected_report_sha256[label]) for label in ("A", "B")}
    emitter_path = str(Path(emitter.__file__).resolve())
    emitter_pin = _sha(Path(emitter_path).read_bytes())
    _need(all(report["producer_pins"].get(emitter_path) == emitter_pin for report in replayed.values()),
          "replayed emitter producer pin mismatch")
    raw, layout = _joint_source(replayed, emitter)
    _need(_sha(Path(emitter_path).read_bytes()) == emitter_pin and
          _sha(Path(__file__).read_bytes()) == _SELF_PIN, "composition source changed")
    return {"schema": SCHEMA, "profile": PROFILE, "lean_source": raw.decode("utf-8"),
        "lean_source_sha256": _sha(raw), "lean_source_bytes": len(raw), "rendering": layout,
        "request_sha256": dict(expected_request_sha256), "report_sha256": dict(expected_report_sha256),
        "producer_pins": {str(Path(__file__).resolve()): _SELF_PIN, emitter_path: emitter_pin},
        "conditional_theorems": list(THEOREMS), "assumptions": list(ASSUMPTIONS),
        "authority": dict(AUTHORITY), "selected_interpretation": None,
        "governing_definition_use": None, "training_mask": 0, "evaluation_gold_mask": 0,
        "source_translation_performed": False, "current_source_or_definition_replay_performed": False,
        "kernel_compilation_performed": False, "native_build_executed": False,
        "proof_checked": False, "model_executed": False, "training_executed": False,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0}


__all__ = ["prepare_full_norm_consequences_v1"]


def _actual_shape(report,label):
    _need(report['profile']=='authored-object-relational-deontic/v1' and report['counts']=={
         'modal_nodes':1,'nodes':15,'predicate_occurrences':3,'quantifiers':3},'complete retained actual relational node population required')
    _need(_wire(report['argument_roles'])==_wire([{'roles':['recipient','duties'],'symbol':'Assign'},
        {'roles':['recipient','duties'],'symbol':'Transfer'},{'roles':['approver','recipient'],'symbol':'Approve'}]),
        'exact actual arity2 ordered role declarations required')
    root=report['native_ast']
    for name in ('r','d','s'):
        _need(set(root)=={'node_type','quantifier','variable','formula'} and root['node_type']=='QuantifiedFormula'
             and _wire(root['quantifier'])==_wire({'enum':'Quantifier','value':'∀'})
             and _wire(root['variable'])==_wire({'name':name,'node_type':'Variable','sort':None}),
             'exact retained universal binder order/carrier required')
        root=root['formula']
    def binary(node,operator):
        _need(set(node)=={'node_type','operator','left','right'} and node['node_type']=='BinaryFormula'
             and _wire(node['operator'])==_wire({'enum':'LogicOperator','value':operator}),'exact retained binary constructor')
    def modal(node):
        _need(set(node)=={'node_type','operator','agent','context','formula'} and node['node_type']=='DeonticFormula'
             and _wire(node['operator'])==_wire({'enum':'DeonticOperator','value':'P'})
             and node['agent'] is None and node['context'] is None,'exact P without agent/context annotations required')
    if label=='A':binary(root,'→');modal(root['left']);actions=root['left']['formula'];approval=root['right'];condition=root['left']
    else:modal(root);binary(root['formula'],'→');actions=root['formula']['left'];approval=root['formula']['right'];condition=root
    binary(actions,'∨')
    def atom(node,name,args):
        _need(_wire(node)==_wire({'node_type':'Predicate','name':name,'arguments':[
            {'name':arg,'node_type':'Variable','sort':None} for arg in args]}),'exact ordered actual predicate arguments required')
    atom(actions['left'],'Assign',('r','d'));atom(actions['right'],'Transfer',('r','d'));atom(approval,'Approve',('s','r'))
    _need(report['source_binding'] is None and all(count > 0 for count in _unprivileged(report))
         and report['source_bound'] is False and report['source_translation_performed'] is False
         and report['native_build_executed'] is False and report['human_reviews']==report['signatures_constructed']==report['admissions']==0,
         'original unreviewed preparation flags must stay unchanged')
    return {'core':root,'actions':actions,'approval':approval,'condition':condition}


def _joint_source(reports,emitter):
    """Use existing renderer only, retaining both whole original declaration strings."""
    shapes={label:_actual_shape(reports[label],label) for label in ('A','B')};environment={'r':'r','d':'d','s':'s'}
    renderer=lambda node:emitter.FormulaRenderer().formula(node,environment)
    a_condition=renderer(shapes['A']['condition']);approval=renderer(shapes['A']['approval'])
    b_modal=renderer(shapes['B']['core']);b_plain=renderer(shapes['B']['core']['formula'])
    _need(_wire(shapes['A']['actions'])==_wire(shapes['B']['actions']) and _wire(shapes['A']['approval'])==_wire(shapes['B']['approval']),
         'A/B must retain literal common ordered actions/approval subtrees')
    source='namespace LegalFullNorms\n'+emitter.PRELUDE+'\nnamespace CandidateA\n'+reports['A']['lean_body']+'\n'
    source+='def permittedActionsAt {Entity Agent : Type} (i : Interpretation Entity Agent) (r d : Entity) : Nat → Prop := '+a_condition+'\n'
    source+='def approvalAt {Entity Agent : Type} (i : Interpretation Entity Agent) (s r : Entity) : Nat → Prop := '+approval+'\n'
    source+=('theorem norm_instance {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (r d s : Entity)\n'
        '    (hNorm : formula_0 i t) : permittedActionsAt i r d t → approvalAt i s r t := by\n'
        '  exact hNorm r d s\n#print axioms norm_instance\n'
        'theorem approval_from_permission {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (r d s : Entity)\n'
        '    (hNorm : formula_0 i t) (hPermit : permittedActionsAt i r d t) : approvalAt i s r t := by\n'
        '  exact hNorm r d s hPermit\n#print axioms approval_from_permission\nend CandidateA\nnamespace CandidateB\n')
    source+=reports['B']['lean_body']+'\n'
    source+='def permittedImplicationAt {Entity Agent : Type} (i : Interpretation Entity Agent) (r d s : Entity) : Nat → Prop := '+b_modal+'\n'
    source+=('theorem modal_instance {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (r d s : Entity)\n'
        '    (hNorm : formula_0 i t) : permittedImplicationAt i r d s t := by\n'
        '  exact hNorm r d s\n#print axioms modal_instance\nend CandidateB\nend LegalFullNorms\n')
    raw=source.encode();slices={}
    for label in ('A','B'):
        body=reports[label]['lean_body'].encode();_need(raw.count(body)==1,'whole original emitted declaration must occur once')
        start=raw.index(body);slices[label]={'byte_start':start,'byte_end':start+len(body),'sha256':_sha(body),'bytes':len(body)}
    return raw,{'emitted_body_slices':slices,'a_condition':a_condition,'approval':approval,'b_modal':b_modal,'b_plain':b_plain,
        'shared_interpretation_prelude_instances':1,'namespaces':{'A':'LegalFullNorms.CandidateA','B':'LegalFullNorms.CandidateB'}}
