"""Authored composition diagnostics; no natural-corpus or proof-quality claim.

Each five-by-five grid keeps all polarities, formatting variants and object
variants together. Evaluation text/targets are only constructed on an explicit
test/canary request. Source metadata is never part of the generated target.
"""
from __future__ import annotations
import ast
import hashlib
import json

SCHEMA = "authored-source-ir-composition/v2"
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
MODALS = ("required", "permitted", "prohibited")
SURFACES = (("must", "may", "must not"),
            ("is required to", "is allowed to", "is forbidden to"))


def split_for(i, j):
    return "test" if i == j else "validation" if j == (i + 1) % 5 else "train"


def manifest():
    return {"schema": SCHEMA, "groups": [dict(domain=d, row=i, column=j, split=split_for(i, j))
        for d in DOMAINS for i in range(5) for j in range(5)],
        "training_rows_per_domain": 180, "validation_rows_per_domain": 60,
        "test_rows_per_domain": 60, "canary_rows_per_domain": 30,
        "test_groups_per_domain": 5, "canary_groups_shared_with_test": True,
        "split_unit": "complete grid cell, including polarity and wording variants",
        "source_semantics_independently_verified": False, "proof_authority": False,
        "real_world_corpus": False}


def _row(domain, i, j, slot, style, split, text, target, metadata=None):
    raw = text.encode()
    return dict(id=f"{domain}:{i}:{j}:{slot}:{style}", group_id=f"{domain}:{i}:{j}",
        split=split, wording_style=style, source_text=text,
        source_sha256=hashlib.sha256(raw).hexdigest(), target=target,
        reference_metadata=metadata or {}, source_semantics_verified=False, proof_authority=False)


def _intent_or_legal(domain, i, j, style, split):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as legal
    if domain == "intent_ir":
        actors = ("curator", "planner", "assessor", "steward", "librarian")
        actions = ("catalog", "verify", "index", "dispatch", "reconcile")
        objects = ("invoice", "summary")
    else:
        actors = ("registrar", "trustee", "secretary", "treasurer", "notary")
        actions = ("approve", "preserve", "publish", "examine", "deliver")
        objects = ("notice", "archive")
    actor, action = actors[i], actions[j]
    result = []
    for oi, object_ in enumerate(objects):
        for mi, modality in enumerate(MODALS):
            modal = SURFACES[style if style < 2 else 0][mi]
            text = f"The {actor} {modal} {action} the {object_}."
            if style == 2:
                text = "By policy, " + text[0].lower() + text[1:]
            if domain == "intent_ir":
                document = dict(kind="atom", actor=actor, action=action, object=object_, modality=modality)
                target = dict(kind="intent_rich_ast", document=document)
                native.validate_target(domain, target)
                if style < 2:
                    from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction
                    assert parse_instruction(text) == document
            else:
                target = {"rules": [dict(modality=("O", "P", "F")[mi], actor=actor, action=action,
                    object=object_, conditions=[], exceptions=[], temporal=[])]}
                legal._rule(target)
            result.append(_row(domain, i, j, oi * 3 + mi, style, split, text, target,
                dict(authored_polarity=modality, reference_scope="single authored modal proposition")))
    return result


def _security(i, j, style, split):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as native
    from ipfs_datasets_py.logic.software_verification.program import ProgramExpression
    names = ("amount", "count", "offset", "value", "limit")
    pairs = (("<", "<="), (">", ">="), ("==", "!="), ("+", "-"), ("*", "//"))
    ast_ops = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==",
               ast.NotEq: "!=", ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.FloorDiv: "//"}
    name = names[i]
    result = []
    for op_index, operator in enumerate(pairs[j]):
        for fn_index, function in enumerate(("compute", "evaluate", "combine")):
            if style == 0:
                text = f"def {function}({name}, bound):\n    return {name} {operator} bound\n"
            elif style == 1:
                text = f"def {function}({name}, bound):\n    # Compute the requested result.\n    return ({name} {operator} bound)\n"
            else:
                text = f"def {function}({name}, bound):\n    result = {name} {operator} bound\n    return result\n"
            function_ast = ast.parse(text).body[0]
            expression = function_ast.body[0].value
            actual_operator = ast_ops[type(expression.ops[0] if isinstance(expression, ast.Compare) else expression.op)]
            assert actual_operator == operator
            operands = ("expr:" + name, "expr:bound")
            target = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary",
                "boolean" if j < 3 else "integer", operand_ids=operands, operator=operator,
                evaluation_order=operands, source_ref_ids=("source",)).to_dict())
            native.validate_target("security_ir", target)
            result.append(_row("security_ir", i, j, op_index * 3 + fn_index, style, split, text, target,
                dict(authored_operator=operator, operand_names=[name, "bound"],
                    reference_scope="local return-expression fragment; enclosing program required",
                    enclosing_program_verified=False)))
    return result


def _ui(i, j, style, split):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as native
    component = ("accept", "dismiss", "lookup", "toggle", "notify")[i]
    role = ("button", "link", "checkbox", "textbox", "alert")[j]
    result = []
    for pi, privacy in enumerate(("none", "sensitive", "restricted")):
        for ci, classification in enumerate(("interactive", "informational")):
            if style == 0:
                text = f"The {component} component has the {role} role. Its privacy sensitivity is {privacy}, and its presentation classification is {classification}."
            elif style == 1:
                text = f"Use role {role} for component {component}; set privacy sensitivity to {privacy} and presentation classification to {classification}."
            else:
                text = f"Component {component}: role {role}; presentation classification {classification}; privacy sensitivity {privacy}."
            target = dict(kind="ui_component", document=dict(component_id=component, role=role,
                privacy_sensitivity=privacy, presentation_classification=classification))
            native.validate_target("ui_ux_ir", target)
            result.append(_row("ui_ux_ir", i, j, pi * 2 + ci, style, split, text, target,
                               dict(reference_scope="authored component declaration, not accessibility compliance")))
    return result


def rows(domain, split):
    if domain not in DOMAINS or split not in {"train", "validation", "test", "canary"}:
        raise ValueError("explicit supported domain and partition required")
    result = []
    for i in range(5):
        for j in range(5):
            if split_for(i, j) != ("test" if split == "canary" else split):
                continue
            for style in ((2,) if split == "canary" else (0, 1)):
                result.extend(_intent_or_legal(domain, i, j, style, split) if domain in {"intent_ir", "legal_ir"}
                    else _security(i, j, style, split) if domain == "security_ir" else _ui(i, j, style, split))
    assert len(result) == {"train": 180, "validation": 60, "test": 60, "canary": 30}[split]
    assert len({row["source_sha256"] for row in result}) == len(result)
    return result
