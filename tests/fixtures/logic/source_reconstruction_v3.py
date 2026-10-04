"""Fresh authored groups for native-valid source reconstruction diagnostics.

Partitions are generated only on explicit request. This is not a natural-corpus
test. Related wording, function-name and polarity variants share a split group.
"""
from __future__ import annotations

import hashlib

DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
SCHEMA = "authored-source-native-composition/v3"


def split_for(i, j):
    return "test" if j == (i + 2) % 5 else "validation" if j == (i + 3) % 5 else "train"


def manifest():
    return dict(schema=SCHEMA, groups_per_domain={"train": 15, "validation": 5, "test": 5},
        variants_per_group_per_style=6, baseline_styles=[0, 1], augmented_styles=[0, 1, 2, 3],
        validation_styles=[0, 1, 2, 3], test_styles=[0, 1, 2, 3], canary_styles=[4, 5],
        canary_groups_shared_with_test=True, real_world_corpus=False,
        split_unit="complete semantic composition group including polarities and wording variants")


def _modal(domain, i, j, style):
    if domain == "intent_ir":
        actor = ("dispatcher", "archivist", "inspector", "coordinator", "reviewer")[i]
        action = ("assemble", "route", "validate", "classify", "record")[j]
        objects = ("manifest", "schedule")
    else:
        actor = ("custodian", "clerk", "commissioner", "executor", "officer")[i]
        action = ("retain", "issue", "inspect", "register", "certify")[j]
        objects = ("certificate", "filing")
    for oi, object_ in enumerate(objects):
        for mi, modality in enumerate(("required", "permitted", "prohibited")):
            surface = ("must", "may", "must not")[mi]
            if style == 0:
                source = f"The {actor} {surface} {action} the {object_}."
            elif style == 1:
                surface = ("is required to", "is allowed to", "is forbidden to")[mi]
                source = f"The {actor} {surface} {action} the {object_}."
            elif style == 2:
                source = f"Under this policy, the {actor} {surface} {action} the {object_}."
            elif style == 3:
                surface = ("is required", "is permitted", "is prohibited")[mi]
                source = f"For the {actor}, the action to {action} the {object_} {surface}."
            elif style == 4:
                source = f"The policy states that the {actor} {surface} {action} the {object_}."
            else:
                surface = ("is mandatory", "is allowed", "is forbidden")[mi]
                source = f"For the {actor}, to {action} the {object_} {surface}."
            target = (dict(kind="intent_rich_ast", document=dict(kind="atom", actor=actor, action=action,
                        object=object_, modality=modality)) if domain == "intent_ir" else
                dict(rules=[dict(modality=("O", "P", "F")[mi], actor=actor, action=action, object=object_,
                                 conditions=[], exceptions=[], temporal=[])]))
            yield oi * 3 + mi, source, target


def _security(i, j, style):
    from ipfs_datasets_py.logic.software_verification.program import ProgramExpression
    name = ("capacity", "volume", "position", "length", "quantity")[i]
    operators = (("<", "<="), (">", ">="), ("==", "!="), ("+", "-"), ("*",))[j]
    functions = ("derive", "assess", "resolve", "calculate", "process", "measure")[:6 // len(operators)]
    for op_index, operator in enumerate(operators):
        for fn_index, function in enumerate(functions):
            header = f"def {function}({name}: int, threshold: int) -> {'bool' if j < 3 else 'int'}:\n"
            expression = f"{name} {operator} threshold"
            if style == 0:
                source = header + f"    return {expression}\n"
            elif style == 1:
                source = header + f"    # Evaluate the requested expression.\n    return ({expression})\n"
            elif style == 2:
                source = header + f"    outcome = {expression}\n    return outcome\n"
            elif style == 3:
                source = header + f"    # Keep the computed value.\n    answer = ({expression})\n    return answer\n"
            elif style == 4:
                source = header + f"    return (\n        {expression}\n    )\n"
            else:
                source = header + f"\tcomputed = ( {expression} )\n\t# Return the intermediate value unchanged.\n\treturn computed\n"
            operands = ("expr:" + name, "expr:threshold")
            target = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary",
                "boolean" if j < 3 else "integer", operand_ids=operands, operator=operator,
                evaluation_order=operands, source_ref_ids=("source",)).to_dict())
            yield op_index * len(functions) + fn_index, source, target


def _ui(i, j, style):
    component = ("confirm", "cancel", "search", "expand", "refresh")[i]
    role = ("slider", "menuitem", "switch", "progressbar", "radio")[j]
    for pi, privacy in enumerate(("none", "high", "restricted")):
        for ci, presentation in enumerate(("interactive", "static")):
            if style == 0:
                source = f"The {component} component has role {role}, privacy sensitivity {privacy}, and presentation classification {presentation}."
            elif style == 1:
                source = f"Set component {component} to role {role}; its privacy sensitivity is {privacy} and its presentation classification is {presentation}."
            elif style == 2:
                source = f"Component {component}: role {role}; presentation classification {presentation}; privacy sensitivity {privacy}."
            elif style == 3:
                source = f"Use privacy sensitivity {privacy} and presentation classification {presentation} for the {component} component with role {role}."
            elif style == 4:
                source = f"For component {component}, assign the role {role}. Choose {presentation} presentation classification and {privacy} privacy sensitivity."
            else:
                source = f"The {component} component uses role {role}. Privacy sensitivity: {privacy}. Presentation classification: {presentation}."
            target = dict(kind="ui_component", document=dict(component_id=component, role=role,
                privacy_sensitivity=privacy, presentation_classification=presentation))
            yield pi * 2 + ci, source, target


def rows(domain, split, *, arm="augmented"):
    if domain not in DOMAINS or split not in ("train", "validation", "test", "canary") or arm not in ("baseline", "augmented"):
        raise ValueError("explicit supported domain/split/arm required")
    styles = (4, 5) if split == "canary" else (0, 1) if split == "train" and arm == "baseline" else (0, 1, 2, 3)
    result = []
    for i in range(5):
        for j in range(5):
            if split_for(i, j) != ("test" if split == "canary" else split):
                continue
            for style in styles:
                content = _modal(domain, i, j, style) if domain in ("intent_ir", "legal_ir") else (
                    _security(i, j, style) if domain == "security_ir" else _ui(i, j, style))
                for slot, text, target in content:
                    result.append(dict(id=f"v3:{domain}:{i}:{j}:{slot}:{style}", group_id=f"v3:{domain}:{i}:{j}",
                        split=split, source_text=text, target=target, wording_style=style,
                        source_sha256=hashlib.sha256(text.encode()).hexdigest()))
    assert len({row["source_sha256"] for row in result}) == len(result)
    return result
