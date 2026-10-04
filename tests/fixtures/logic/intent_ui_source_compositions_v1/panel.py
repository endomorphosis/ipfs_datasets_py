"""Controlled compositions; construct test texts only after all fits are sealed.

The held-out unit is a complete composition, not a new actor, role or word.
Every varying scalar occurs in training. This cannot measure general language
understanding or unrestricted document decoding.
"""
from itertools import product

DOMAINS = ("intent_ir", "ui_ux_ir")
SEEDS = (3517, 3518)
ACTORS = ("archivist", "auditor", "courier", "steward")
ACTIONS = ("index", "transmit", "label", "inspect")
OBJECTS = ("docket", "invoice", "schedule")
MODALITIES = (("must", "required"), ("may", "permitted"), ("must not", "prohibited"))
COMPONENTS = ("approve_toggle", "export_panel", "audit_badge", "search_control")
ROLES = ("button", "checkbox", "listbox", "textbox")
PRIVACIES = ("none", "low", "high")
PRESENTATIONS = ("interactive", "static", "status")


def groups(split):
    if split not in {"train", "tuning", "test"}:
        raise ValueError("unknown split")
    result = []
    for i, j, k, m in product(range(4), range(4), range(3), range(3)):
        chosen = "train" if m != (i + j + k) % 3 else "test" if (i + j + k) % 2 == 0 else "tuning"
        if chosen == split:
            result.append((i, j, k, m))
    return result


def metadata():
    return {"schema": "intent-ui-source-compositions/v1", "domains": list(DOMAINS),
        "seeds": list(SEEDS), "counts_per_domain": {s: len(groups(s)) for s in ("train", "tuning", "test")},
        "split_coordinates": {s: groups(s) for s in ("train", "tuning", "test")},
        "scope": "authored_compositions_of_training_vocabulary_in_one_fixed_schema_per_domain",
        "split_rule": "hold_out_m=(i+j+k)%3; even_i+j+k_test; odd_tuning; remaining_two_m_train",
        "semantic_groups_disjoint": False, "complete_compositions_disjoint": True,
        "unseen_lexical_generalization_tested": False, "full_document_coverage": False}


def rows(split, domain):
    if domain not in DOMAINS:
        raise ValueError("unsupported domain")
    result = []
    for i, j, k, m in groups(split):
        if domain == "intent_ir":
            surface, modality = MODALITIES[m]
            text = f"The {ACTORS[i]} {surface} {ACTIONS[j]} the {OBJECTS[k]}."
            target = {"kind": "intent_rich_ast", "document": {"kind": "atom", "actor": ACTORS[i],
                "action": ACTIONS[j], "object": OBJECTS[k], "modality": modality}}
        else:
            text = (f"Component {COMPONENTS[i]} has role {ROLES[j]}. Its privacy sensitivity is {PRIVACIES[k]} "
                    f"and its presentation classification is {PRESENTATIONS[m]}.")
            target = {"kind": "ui_component", "document": {"component_id": COMPONENTS[i], "role": ROLES[j],
                "privacy_sensitivity": PRIVACIES[k], "presentation_classification": PRESENTATIONS[m]}}
        result.append({"id": f"intent-ui-composition-v1:{domain}:{i}:{j}:{k}:{m}",
                       "source_text": text, "target": target})
    return result


def critical_paths(domain):
    if domain == "intent_ir":
        fields = ("actor", "action", "object", "modality")
    elif domain == "ui_ux_ir":
        fields = ("component_id", "role", "privacy_sensitivity", "presentation_classification")
    else:
        raise ValueError("unsupported domain")
    return tuple(("document", field) for field in fields)
